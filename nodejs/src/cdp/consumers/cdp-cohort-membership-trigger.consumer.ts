import { chunk } from 'lodash'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, START_AT_LATEST, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { HealthCheckResult, PluginsServerConfig, Team } from '../../types'
import { HogFlow } from '../schema/hogflow'
import { PRODUCER_VERSION_FORMAT } from '../services/cohort-membership/sweeper.service'
import {
    COHORT_MEMBERSHIP_CHANGED_EVENT,
    COHORT_MEMBERSHIP_VERSION_PROPERTY,
} from '../services/cohorts/cohort-membership-repository'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CohortMembershipChange, CohortMembershipChangeSchema } from './cdp-cohort-membership.consumer'
import { assertTeamId, skipIfMalformed } from './message-parsing'

export const counterCohortMembershipTriggerSkipped = new Counter({
    name: 'cdp_cohort_membership_trigger_skipped',
    help: 'Membership changes the cohort trigger consumer did not turn into workflow runs, by reason.',
    labelNames: ['reason'],
})

export function isMatchingCohortTrigger(flow: HogFlow, globals: HogFunctionInvocationGlobals): boolean {
    const trigger = flow.trigger
    return (
        trigger.type === 'cohort' &&
        globals.event.event === COHORT_MEMBERSHIP_CHANGED_EVENT &&
        trigger.cohort_id === globals.event.properties.cohort_id &&
        trigger.transition === globals.event.properties.status
    )
}

/**
 * A join or a leave as a `$cohort_membership_changed` event for the person. The change carries no
 * distinct_id and no person properties, so the event has neither.
 */
export function convertCohortMembershipChangeToGlobals(
    change: CohortMembershipChange,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const globals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
        team,
        personId: change.person_id,
        siteUrl,
    })
    globals.event = {
        ...globals.event,
        event: COHORT_MEMBERSHIP_CHANGED_EVENT,
        properties: {
            cohort_id: change.cohort_id,
            status: change.status,
            // An off-format stamp can't be bound into the `::timestamp` comparison.
            ...(change.last_updated && PRODUCER_VERSION_FORMAT.test(change.last_updated)
                ? { [COHORT_MEMBERSHIP_VERSION_PROPERTY]: change.last_updated }
                : {}),
        },
    }
    return globals
}

/**
 * Starts workflow runs from realtime cohort membership changes.
 *
 * Reads the same topic as CdpCohortMembershipConsumer under its own group, so persisting membership
 * and starting runs fail and lag independently.
 */
export class CdpCohortMembershipTriggerConsumer extends CdpConsumerBase {
    protected name = 'CdpCohortMembershipTriggerConsumer'

    protected hogflowQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFlowPipeline: HogFlowInvocationPipeline
    private queueConfig: Pick<
        PluginsServerConfig,
        'CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE' | 'CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES'
    >

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueues: { hogflowQueue: JobQueue }) {
        super(config, deps)
        this.hogflowQueue = jobQueues.hogflowQueue
        this.queueConfig = config
        // A fresh group starts at the tip. Replaying the retained topic would start runs for old changes.
        this.kafkaConsumer = createKafkaConsumer(
            { groupId: 'cdp-cohort-membership-trigger-consumer', topic: KAFKA_COHORT_MEMBERSHIP_CHANGED },
            START_AT_LATEST
        )
        this.hogFlowPipeline = new HogFlowInvocationPipeline(config, {
            hogFlowManager: this.hogFlowManager,
            hogFlowExecutor: this.hogFlowExecutor,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        const { invocations, release } = await this.hogFlowPipeline.buildInvocationsWithRelease(invocationGlobals, {
            eligibilityFn: isMatchingCohortTrigger,
        })

        for (const invocation of invocations) {
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        return {
            backgroundTask: Promise.all([
                instrumentFn(
                    { key: 'cdp.background_task.queue_hogflow_invocations', sendException: false },
                    async () => {
                        // One insert per chunk, so a failure leaves a known set of runs queued.
                        const batches = chunk(invocations, this.queueConfig.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)
                        const queued: CyclotronJobInvocation[] = []
                        let failure: { error: unknown } | null = null
                        if (this.queueConfig.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                            const results = await Promise.allSettled(
                                batches.map((batch) => this.hogflowQueue.queueInvocations(batch))
                            )
                            results.forEach((result, index) => {
                                if (result.status === 'fulfilled') {
                                    queued.push(...batches[index])
                                } else {
                                    failure ??= { error: result.reason }
                                }
                            })
                        } else {
                            for (const batch of batches) {
                                try {
                                    await this.hogflowQueue.queueInvocations(batch)
                                    queued.push(...batch)
                                } catch (error) {
                                    failure = { error }
                                    break
                                }
                            }
                        }
                        if (failure) {
                            // The batch is retried. Runs that never reached the queue release their claims, or the
                            // retry finds them masked. Queued runs keep theirs, so their people do not run twice.
                            await release(queued)
                            const queuedIds = new Set(queued.map((invocation) => invocation.id))
                            this.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor(
                                invocations
                                    .filter((invocation) => !queuedIds.has(invocation.id))
                                    .map((invocation) => invocation.id)
                            )
                            throw failure.error
                        }
                    }
                ),
                instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                    try {
                        await this.hogFunctionMonitoringService.flush()
                    } catch (err) {
                        captureException(err)
                        logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                    }
                }),
                instrumentFn({ key: 'cdp.background_task.lifecycle_running_flush', sendException: false }, () =>
                    this.invocationResultsService.invocationResultsRowsService.flush()
                ),
            ]),
            invocations,
        }
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const changes: CohortMembershipChange[] = []
        for (const message of messages) {
            const change = skipIfMalformed('Error parsing cohort membership change', () =>
                assertTeamId(CohortMembershipChangeSchema.parse(parseJSON(message.value!.toString())))
            )
            if (!change) {
                continue
            }

            // Seed and reconcile messages restate membership the cohort already had. Starting runs
            // on them would put every existing member through the workflow when a cohort is built.
            if (change.origin) {
                counterCohortMembershipTriggerSkipped.labels({ reason: 'backfill' }).inc()
                continue
            }
            changes.push(change)
        }

        // One lookup per team per batch: a cohort recompute fills whole batches with one team's changes.
        // Load errors propagate, so the batch fails, the offsets stay put and the consumer retries.
        const teamIds = [...new Set(changes.map((change) => change.team_id))]
        const hogFlowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamIds)

        const events: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            changes.map(async (change) => {
                const triggered = (hogFlowsByTeam[change.team_id] ?? []).some(
                    (flow) => flow.trigger.type === 'cohort' && flow.trigger.cohort_id === change.cohort_id
                )
                if (!triggered) {
                    return
                }

                const team = await this.deps.teamManager.getTeam(change.team_id)
                if (!team) {
                    // The team has active cohort-triggered workflows, so a missing team means the lookup is broken.
                    logger.warn('Team not found for a cohort membership change', { teamId: change.team_id })
                    counterCohortMembershipTriggerSkipped.labels({ reason: 'team_not_found' }).inc()
                    return
                }

                events.push(convertCohortMembershipChangeToGlobals(change, team, this.config.SITE_URL))
            })
        )

        return events
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.hogflowQueue.startAsProducer()
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, { size: messages.length })
            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(invocationGlobals)
                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        await this.hogflowQueue.stopProducer()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

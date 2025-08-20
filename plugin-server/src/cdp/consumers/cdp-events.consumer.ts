import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    HogFunctionTypeType,
    MinimalAppMetric,
} from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export const counterMissingAddon = new Counter({
    name: 'cdp_function_missing_addon',
    help: 'A function invocation was missing an addon',
    labelNames: ['team_id'],
})

export const counterQuotaLimited = new Counter({
    name: 'cdp_function_quota_limited',
    help: 'A function invocation was quota limited',
    labelNames: ['team_id'],
})

export const counterHogFunctionStateOnEvent = new Counter({
    name: 'cdp_hog_function_state_on_event',
    help: 'Metric the state of a hog function that matched an event',
    labelNames: ['state', 'kind'],
})

export class CdpEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumer

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-processed-events-consumer') {
        super(hub)
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hog')
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        const invocationsToBeQueued = [
            ...(await this.createHogFunctionInvocations(invocationGlobals)),
            ...(await this.createHogFlowInvocations(invocationGlobals)),
        ]

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([
                this.cyclotronJobQueue.queueInvocations(invocationsToBeQueued),
                this.hogFunctionMonitoringService.produceQueuedMessages().catch((err) => {
                    captureException(err)
                    logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                }),
            ]),
            invocations: invocationsToBeQueued,
        }
    }

    protected filterHogFunction(hogFunction: HogFunctionType): boolean {
        // By default we filter for those with no filters or filters specifically for events
        return (hogFunction.filters?.source ?? 'events') === 'events'
    }

    /**
     * Finds all matching hog functions for the given globals.
     * Filters them for their disabled state as well as masking configs
     */
    protected async createHogFunctionInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<CyclotronJobInvocation[]> {
        return await this.runInstrumented('handleEachBatch.queueMatchingFunctions', async () => {
            // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
            await this.groupsManager.enrichGroups(invocationGlobals)

            const teamsToLoad = [...new Set(invocationGlobals.map((x) => x.project.id))]
            const [hogFunctionsByTeam, teamsById] = await Promise.all([
                this.hogFunctionManager.getHogFunctionsForTeams(teamsToLoad, this.hogTypes, this.filterHogFunction),
                this.hub.teamManager.getTeams(teamsToLoad),
            ])

            const possibleInvocations = (
                await Promise.all(
                    invocationGlobals.map(async (globals) => {
                        const teamHogFunctions = hogFunctionsByTeam[globals.project.id]

                        const { invocations, metrics, logs } = await this.hogExecutor.buildHogFunctionInvocations(
                            teamHogFunctions,
                            globals
                        )

                        this.hogFunctionMonitoringService.queueAppMetrics(metrics, 'hog_function')
                        this.hogFunctionMonitoringService.queueLogs(logs, 'hog_function')
                        this.heartbeat()

                        return invocations
                    })
                )
            ).flat()

            const states = await this.hogWatcher.getEffectiveStates(possibleInvocations.map((x) => x.hogFunction.id))
            const validInvocations: CyclotronJobInvocationHogFunction[] = []

            // Iterate over adding them to the list and updating their priority
            for (const item of possibleInvocations) {
                // Disable invocations for teams that don't have the addon (for now just metric them out..)

                const isQuotaLimited = await this.hub.quotaLimiting.isTeamQuotaLimited(item.teamId, 'cdp_invocations')

                // The legacy addon was not usage based so we skip dropping if they are on it
                const isTeamOnLegacyAddon = !!teamsById[`${item.teamId}`]?.available_features.includes('data_pipelines')

                if (isQuotaLimited && !isTeamOnLegacyAddon) {
                    counterQuotaLimited.labels({ team_id: item.teamId }).inc()

                    // TODO: Once happy - we add the below code to track a quota limited metric and skip the invocation

                    // this.hogFunctionMonitoringService.queueAppMetric(
                    //     {
                    //         team_id: item.teamId,
                    //         app_source_id: item.functionId,
                    //         metric_kind: 'failure',
                    //         metric_name: 'quota_limited',
                    //         count: 1,
                    //     },
                    //     'hog_function'
                    // )
                    // continue
                }

                if (
                    !teamsById[`${item.teamId}`]?.available_features.includes('data_pipelines') &&
                    item.hogFunction.is_addon_required
                ) {
                    // NOTE: This will be removed in favour of the quota limited metric
                    counterMissingAddon.labels({ team_id: item.teamId }).inc()
                }

                const state = states[item.hogFunction.id].state

                counterHogFunctionStateOnEvent
                    .labels({
                        state: HogWatcherState[state],
                        kind: item.hogFunction.type,
                    })
                    .inc()

                if (state === HogWatcherState.disabled) {
                    this.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: item.teamId,
                            app_source_id: item.functionId,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        },
                        'hog_function'
                    )
                    continue
                }

                if (state === HogWatcherState.degraded) {
                    item.queuePriority = 2
                    if (this.hub.CDP_OVERFLOW_QUEUE_ENABLED) {
                        item.queue = 'hog_overflow'
                    }
                }

                validInvocations.push(item)
            }

            // Now we can filter by masking configs
            const { masked, notMasked: notMaskedInvocations } = await this.hogMasker.filterByMasking(validInvocations)

            this.hogFunctionMonitoringService.queueAppMetrics(
                masked.map((item) => ({
                    team_id: item.teamId,
                    app_source_id: item.functionId,
                    metric_kind: 'other',
                    metric_name: 'masked',
                    count: 1,
                })),
                'hog_function'
            )

            const billingMetrics = Object.values(notMaskedInvocations)
                .filter((inv) => inv.hogFunction.type === 'destination')
                .map((inv): MinimalAppMetric => {
                    return {
                        metric_kind: 'billing',
                        metric_name: 'billable_invocation',
                        team_id: inv.teamId,
                        app_source_id: inv.hogFunction.id,
                        count: 1,
                    }
                })

            this.hogFunctionMonitoringService.queueAppMetrics(billingMetrics, 'hog_function')

            return notMaskedInvocations
        })
    }

    /**
     * Finds all matching hog flows for the given globals.
     * Filters them for their disabled state as well as masking configs
     */
    protected async createHogFlowInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<CyclotronJobInvocation[]> {
        return await this.runInstrumented('handleEachBatch.queueMatchingFlows', async () => {
            // TODO: Add back in group enrichment if necessary
            // await this.groupsManager.enrichGroups(invocationGlobals)

            const teamsToLoad = [...new Set(invocationGlobals.map((x) => x.project.id))]
            const hogFlowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamsToLoad)

            const possibleInvocations = (
                await Promise.all(
                    invocationGlobals.map(async (globals) => {
                        const teamHogFlows = hogFlowsByTeam[globals.project.id]

                        const { invocations, metrics, logs } = await this.hogFlowExecutor.buildHogFlowInvocations(
                            teamHogFlows,
                            globals
                        )

                        this.hogFunctionMonitoringService.queueAppMetrics(metrics, 'hog_flow')
                        this.hogFunctionMonitoringService.queueLogs(logs, 'hog_flow')
                        this.heartbeat()

                        return invocations
                    })
                )
            ).flat()

            const states = await this.hogWatcher.getEffectiveStates(possibleInvocations.map((x) => x.hogFlow.id))
            const validInvocations: CyclotronJobInvocation[] = []

            // Iterate over adding them to the list and updating their priority
            possibleInvocations.forEach((item) => {
                const state = states[item.hogFlow.id].state
                if (state === HogWatcherState.disabled) {
                    this.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: item.teamId,
                            app_source_id: item.functionId,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        },
                        'hog_flow'
                    )
                    return
                }

                if (state === HogWatcherState.degraded) {
                    item.queuePriority = 2
                }

                validInvocations.push(item)
            })

            // TODO: Add back in Masking options

            return validInvocations
        })
    }

    // This consumer always parses from kafka
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
                    const events: HogFunctionInvocationGlobals[] = []

                    await Promise.all(
                        messages.map(async (message) => {
                            try {
                                const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                                const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                                    this.hogFunctionManager.getHogFunctionsForTeam(
                                        clickHouseEvent.team_id,
                                        this.hogTypes
                                    ),
                                    this.hogFlowManager.getHogFlowsForTeam(clickHouseEvent.team_id),
                                    this.hub.teamManager.getTeam(clickHouseEvent.team_id),
                                ])

                                if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                                    return
                                }

                                events.push(
                                    convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.hub.SITE_URL)
                                )
                            } catch (e) {
                                logger.error('Error parsing message', e)
                                counterParseError.labels({ error: e.message }).inc()
                            }
                        })
                    )

                    return events
                },
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await this.cyclotronJobQueue.startAsProducer()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(invocationGlobals)

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Stopping cyclotron job queue...')
        await this.cyclotronJobQueue.stop()
        logger.info('💤', 'Stopping consumer...')
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}

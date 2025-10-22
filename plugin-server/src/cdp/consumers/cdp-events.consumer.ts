import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogRateLimiterService } from '../services/monitoring/hog-rate-limiter.service'
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

const counterQuotaLimited = new Counter({
    name: 'cdp_function_quota_limited',
    help: 'A function invocation was quota limited',
    labelNames: ['team_id'],
})

const counterRateLimited = new Counter({
    name: 'cdp_function_rate_limited',
    help: 'A function invocation was rate limited',
    labelNames: ['kind'],
})

const counterHogFunctionStateOnEvent = new Counter({
    name: 'cdp_hog_function_state_on_event',
    help: 'Metric the state of a hog function that matched an event',
    labelNames: ['state', 'kind'],
})

export class CdpEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumer

    private hogRateLimiter: HogRateLimiterService

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-processed-events-consumer') {
        super(hub)
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hog')
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.hogRateLimiter = new HogRateLimiterService(hub, this.redis)
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
                this.hogFunctionMonitoringService.flush().catch((err) => {
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
    @instrumented('cdpConsumer.handleEachBatch.queueMatchingFunctions')
    protected async createHogFunctionInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<CyclotronJobInvocation[]> {
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

        const states = await instrumentFn('cdpConsumer.handleEachBatch.hogWatcher.getEffectiveStates', async () => {
            return await this.hogWatcher.getEffectiveStates(possibleInvocations.map((x) => x.hogFunction.id))
        })
        const rateLimits = await instrumentFn('cdpConsumer.handleEachBatch.hogRateLimiter.rateLimitMany', async () => {
            return await this.hogRateLimiter.rateLimitMany(possibleInvocations.map((x) => [x.hogFunction.id, 1]))
        })

        const validInvocations: CyclotronJobInvocationHogFunction[] = []

        // Iterate over adding them to the list and updating their priority
        await Promise.all(
            possibleInvocations.map(async (item, index) => {
                // Disable invocations for teams that don't have the addon (for now just metric them out..)

                try {
                    const rateLimit = rateLimits[index][1]
                    if (rateLimit.isRateLimited) {
                        counterRateLimited.labels({ kind: 'hog_function' }).inc()
                        // NOTE: We don't return here as we are just monitoring this feature currently
                        // this.hogFunctionMonitoringService.queueAppMetric(
                        //     {
                        //         team_id: item.teamId,
                        //         app_source_id: item.functionId,
                        //         metric_kind: 'failure',
                        //         metric_name: 'rate_limited',
                        //         count: 1,
                        //     },
                        //     'hog_function'
                        // )
                        // return
                    }
                } catch (e) {
                    captureException(e)
                    logger.error('🔴', 'Error checking rate limit for hog function', { err: e })
                }

                const isQuotaLimited = await this.hub.quotaLimiting.isTeamQuotaLimited(
                    item.teamId,
                    'cdp_trigger_events'
                )

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
                    // return
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
                    return
                }

                if (state === HogWatcherState.degraded) {
                    item.queuePriority = 2
                    if (this.hub.CDP_OVERFLOW_QUEUE_ENABLED) {
                        item.queue = 'hogoverflow'
                    }
                }

                validInvocations.push(item)
            })
        )

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

        const triggeredInvocationsMetrics: MinimalAppMetric[] = []

        notMaskedInvocations.forEach((item) => {
            triggeredInvocationsMetrics.push({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })

            if (item.hogFunction.type === 'destination') {
                triggeredInvocationsMetrics.push({
                    team_id: item.teamId,
                    app_source_id: item.functionId,
                    metric_kind: 'billing',
                    metric_name: 'billable_invocation',
                    count: 1,
                })
            }
        })

        this.hogFunctionMonitoringService.queueAppMetrics(triggeredInvocationsMetrics, 'hog_function')

        return notMaskedInvocations
    }

    /**
     * Finds all matching hog flows for the given globals.
     * Filters them for their disabled state as well as masking configs
     */
    @instrumented('cdpConsumer.handleEachBatch.queueMatchingFlows')
    protected async createHogFlowInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<CyclotronJobInvocation[]> {
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

        const states = await instrumentFn('cdpConsumer.handleEachBatch.hogWatcher.getEffectiveStates', async () => {
            return await this.hogWatcher.getEffectiveStates(possibleInvocations.map((x) => x.hogFlow.id))
        })
        const rateLimits = await instrumentFn('cdpConsumer.handleEachBatch.hogRateLimiter.rateLimitMany', async () => {
            return await this.hogRateLimiter.rateLimitMany(possibleInvocations.map((x) => [x.hogFlow.id, 1]))
        })
        const validInvocations: CyclotronJobInvocation[] = []

        // Iterate over adding them to the list and updating their priority
        possibleInvocations.forEach((item, index) => {
            try {
                const rateLimit = rateLimits[index][1]
                if (rateLimit.isRateLimited) {
                    counterRateLimited.labels({ kind: 'hog_flow' }).inc()
                    this.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: item.teamId,
                            app_source_id: item.functionId,
                            metric_kind: 'failure',
                            metric_name: 'rate_limited',
                            count: 1,
                        },
                        'hog_flow'
                    )
                    return
                }
            } catch (e) {
                captureException(e)
                logger.error('🔴', 'Error checking rate limit for hog flow', { err: e })
            }

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
            'hog_flow'
        )

        const triggeredInvocationsMetrics: MinimalAppMetric[] = []

        notMaskedInvocations.forEach((item) => {
            triggeredInvocationsMetrics.push({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })

            triggeredInvocationsMetrics.push({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'billing',
                metric_name: 'billable_invocation',
                count: 1,
            })
        })

        this.hogFunctionMonitoringService.queueAppMetrics(triggeredInvocationsMetrics, 'hog_flow')

        return notMaskedInvocations
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                    const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(clickHouseEvent.team_id, this.hogTypes),
                        this.hogFlowManager.getHogFlowsForTeam(clickHouseEvent.team_id),
                        this.hub.teamManager.getTeam(clickHouseEvent.team_id),
                    ])

                    if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                        return
                    }

                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.hub.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
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

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
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

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

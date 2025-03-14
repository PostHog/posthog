import { CyclotronManager } from '@posthog/cyclotron'
import { chunk } from 'lodash'
import { Message } from 'node-rdkafka'

import { Hub, RawClickHouseEvent } from '~/src/types'

import {
    convertToHogFunctionInvocationGlobals,
    isLegacyPluginHogFunction,
    serializeHogFunctionInvocation,
} from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { status } from '../../utils/status'
import { HogWatcherState } from '../services/hog-watcher.service'
import { HogFunctionInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

export class CdpProcessedEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpProcessedEventsConsumer'
    protected topic = KAFKA_EVENTS_JSON
    protected groupId = 'cdp-processed-events-consumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private cyclotronManager?: CyclotronManager

    constructor(hub: Hub) {
        super(hub)
    }

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocation[]> {
        if (!invocationGlobals.length) {
            return []
        }

        const invocationsToBeQueued = await this.runWithHeartbeat(() =>
            this.createHogFunctionInvocations(invocationGlobals)
        )

        // For the cyclotron ones we simply create the jobs
        const cyclotronJobs = invocationsToBeQueued.map((item) => {
            return {
                teamId: item.globals.project.id,
                functionId: item.hogFunction.id,
                queueName: isLegacyPluginHogFunction(item.hogFunction) ? 'plugin' : 'hog',
                priority: item.priority,
                vmState: serializeHogFunctionInvocation(item),
            }
        })
        try {
            // Cyclotron batches inserts into one big INSERT which can lead to contention writing WAL information hence we chunk into batches

            const chunkedCyclotronJobs = chunk(cyclotronJobs, this.hub.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)
            if (this.hub.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                // NOTE: It's not super clear if we could do this in parallel
                await Promise.all(chunkedCyclotronJobs.map((jobs) => this.cyclotronManager?.bulkCreateJobs(jobs)))
            } else {
                for (const jobs of chunkedCyclotronJobs) {
                    await this.cyclotronManager?.bulkCreateJobs(jobs)
                }
            }
        } catch (e) {
            status.error('⚠️', 'Error creating cyclotron jobs', e)
            status.warn('⚠️', 'Failed jobs', { jobs: cyclotronJobs })
            throw e
        }

        await this.hogFunctionMonitoringService.produceQueuedMessages()

        return invocationsToBeQueued
    }

    /**
     * Finds all matching hog functions for the given globals.
     * Filters them for their disabled state as well as masking configs
     */
    protected async createHogFunctionInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<HogFunctionInvocation[]> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.queueMatchingFunctions`,
            func: async () => {
                // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
                await this.groupsManager.enrichGroups(invocationGlobals)
                const possibleInvocations = (
                    await this.runManyWithHeartbeat(invocationGlobals, (globals) => {
                        const { invocations, metrics, logs } = this.hogExecutor.findHogFunctionInvocations(globals)

                        this.hogFunctionMonitoringService.produceAppMetrics(metrics)
                        this.hogFunctionMonitoringService.produceLogs(logs)

                        return invocations
                    })
                ).flat()

                const states = await this.hogWatcher.getStates(possibleInvocations.map((x) => x.hogFunction.id))
                const validInvocations: HogFunctionInvocation[] = []

                // Iterate over adding them to the list and updating their priority
                possibleInvocations.forEach((item) => {
                    const state = states[item.hogFunction.id].state
                    if (state >= HogWatcherState.disabledForPeriod) {
                        this.hogFunctionMonitoringService.produceAppMetric({
                            team_id: item.globals.project.id,
                            app_source_id: item.hogFunction.id,
                            metric_kind: 'failure',
                            metric_name:
                                state === HogWatcherState.disabledForPeriod
                                    ? 'disabled_temporarily'
                                    : 'disabled_permanently',
                            count: 1,
                        })
                        return
                    }

                    if (state === HogWatcherState.degraded) {
                        item.priority = 2
                    }

                    validInvocations.push(item)
                })

                // Now we can filter by masking configs
                const { masked, notMasked: notMaskedInvocations } = await this.hogMasker.filterByMasking(
                    validInvocations
                )

                this.hogFunctionMonitoringService.produceAppMetrics(
                    masked.map((item) => ({
                        team_id: item.globals.project.id,
                        app_source_id: item.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'masked',
                        count: 1,
                    }))
                )

                return notMaskedInvocations
            },
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
                                const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent

                                if (!this.hogFunctionManager.teamHasHogDestinations(clickHouseEvent.team_id)) {
                                    // No need to continue if the team doesn't have any functions
                                    return
                                }

                                const team = await this.hub.teamManager.fetchTeam(clickHouseEvent.team_id)
                                if (!team) {
                                    return
                                }
                                events.push(
                                    convertToHogFunctionInvocationGlobals(
                                        clickHouseEvent,
                                        team,
                                        this.hub.SITE_URL ?? 'http://localhost:8000'
                                    )
                                )
                            } catch (e) {
                                status.error('Error parsing message', e)
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
        await this.startKafkaConsumer({
            topic: this.topic,
            groupId: this.groupId,
            handleBatch: async (messages) => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                await this.processBatch(invocationGlobals)
            },
        })

        const shardDepthLimit = this.hub.CYCLOTRON_SHARD_DEPTH_LIMIT ?? 1000000

        this.cyclotronManager = this.hub.CYCLOTRON_DATABASE_URL
            ? new CyclotronManager({ shards: [{ dbUrl: this.hub.CYCLOTRON_DATABASE_URL }], shardDepthLimit })
            : undefined

        await this.cyclotronManager?.connect()
    }
}

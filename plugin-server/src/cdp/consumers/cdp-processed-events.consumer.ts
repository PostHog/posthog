import { CyclotronJobInit, CyclotronManager } from '@posthog/cyclotron'
import { chunk } from 'lodash'
import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import {
    convertToHogFunctionInvocationGlobals,
    isLegacyPluginHogFunction,
    serializeHogFunctionInvocation,
} from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/batch-consumer-v2'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogWatcherState } from '../services/hog-watcher.service'
import { HogFunctionInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export const histogramCyclotronJobsCreated = new Histogram({
    name: 'cdp_cyclotron_jobs_created_per_batch',
    help: 'The number of jobs we are creating in a single batch',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

export class CdpProcessedEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpProcessedEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    protected kafkaConsumer: KafkaConsumer

    private cyclotronManager?: CyclotronManager

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-processed-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    private async createCyclotronJobs(jobs: CyclotronJobInit[]) {
        const cyclotronManager = this.cyclotronManager
        if (!cyclotronManager) {
            throw new Error('Cyclotron manager not initialized')
        }
        return this.runInstrumented('cyclotronManager.bulkCreateJobs', () => cyclotronManager.bulkCreateJobs(jobs))
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
                priority: item.queuePriority,
                vmState: serializeHogFunctionInvocation(item),
            }
        })
        try {
            histogramCyclotronJobsCreated.observe(cyclotronJobs.length)
            // Cyclotron batches inserts into one big INSERT which can lead to contention writing WAL information hence we chunk into batches

            const chunkedCyclotronJobs = chunk(cyclotronJobs, this.hub.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)

            if (this.hub.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                // NOTE: It's not super clear the perf tradeoffs of doing this in parallel hence the config option
                await Promise.all(chunkedCyclotronJobs.map((jobs) => this.createCyclotronJobs(jobs)))
            } else {
                for (const jobs of chunkedCyclotronJobs) {
                    await this.createCyclotronJobs(jobs)
                }
            }
        } catch (e) {
            logger.error('⚠️', 'Error creating cyclotron jobs', e)
            logger.warn('⚠️', 'Failed jobs', { jobs: cyclotronJobs })
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
        return await this.runInstrumented('handleEachBatch.queueMatchingFunctions', async () => {
            // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
            await this.groupsManager.enrichGroups(invocationGlobals)

            const teamsToLoad = [...new Set(invocationGlobals.map((x) => x.project.id))]
            const hogFunctionsByTeam = await this.hogFunctionManager.getHogFunctionsForTeams(teamsToLoad, this.hogTypes)

            const possibleInvocations = (
                await this.runManyWithHeartbeat(invocationGlobals, (globals) => {
                    const teamHogFunctions = hogFunctionsByTeam[globals.project.id]

                    const { invocations, metrics, logs } = this.hogExecutor.buildHogFunctionInvocations(
                        teamHogFunctions,
                        globals
                    )

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
                    item.queuePriority = 2
                }

                validInvocations.push(item)
            })

            // Now we can filter by masking configs
            const { masked, notMasked: notMaskedInvocations } = await this.hogMasker.filterByMasking(validInvocations)

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

                                const [teamHogFunctions, team] = await Promise.all([
                                    this.hogFunctionManager.getHogFunctionsForTeam(clickHouseEvent.team_id, [
                                        'destination',
                                    ]),
                                    this.hub.teamManager.getTeam(clickHouseEvent.team_id),
                                ])

                                if (!teamHogFunctions.length || !team) {
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

        this.cyclotronManager = this.hub.CYCLOTRON_DATABASE_URL
            ? new CyclotronManager({
                  shards: [
                      {
                          dbUrl: this.hub.CYCLOTRON_DATABASE_URL,
                      },
                  ],
                  shardDepthLimit: this.hub.CYCLOTRON_SHARD_DEPTH_LIMIT ?? 1000000,
                  shouldCompressVmState: this.hub.CDP_CYCLOTRON_COMPRESS_VM_STATE,
                  shouldUseBulkJobCopy: this.hub.CDP_CYCLOTRON_USE_BULK_COPY_JOB,
              })
            : undefined

        await this.cyclotronManager?.connect()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                await this.processBatch(invocationGlobals)
            })
        })
    }

    public async stop(): Promise<void> {
        await this.kafkaConsumer.disconnect()
        await super.stop()
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}

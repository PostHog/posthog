import { Message } from 'node-rdkafka'
import { compress } from 'snappy'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_CDP_BACKFILL_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { serializeInvocation } from '../services/job-queue/job-queue-kafka'
import { cdpJobSizeKb } from '../services/job-queue/shared'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { isLegacyPluginHogFunction, isNativeHogFunction, isSegmentPluginHogFunction } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

export class CdpBackfillConsumer extends CdpConsumerBase {
    protected name = 'CdpBackfillConsumer'
    private kafkaConsumer: KafkaConsumer
    private topic: string

    constructor(hub: Hub, topic: string = KAFKA_CDP_BACKFILL_EVENTS, groupId: string = 'cdp-backfill-consumer') {
        super(hub)
        this.topic = topic
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    private async parseKafkaBatch(messages: Message[]): Promise<CyclotronJobInvocation[]> {
        const invocations: CyclotronJobInvocation[] = []

        for (const message of messages) {
            try {
                const invocation = parseJSON(message.value!.toString()) as CyclotronJobInvocation
                invocations.push(invocation)
            } catch (e) {
                logger.error('Error parsing backfill message', { error: e })
            }
        }

        return invocations
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return await Promise.all(
            loadedInvocations.map((item) => {
                if (isNativeHogFunction(item.hogFunction)) {
                    return this.nativeDestinationExecutorService.execute(item)
                } else if (isLegacyPluginHogFunction(item.hogFunction)) {
                    return this.pluginDestinationExecutorService.execute(item)
                } else if (isSegmentPluginHogFunction(item.hogFunction)) {
                    return this.segmentDestinationExecutorService.execute(item)
                } else {
                    return this.hogExecutor.executeWithAsyncFunctions(item)
                }
            })
        )
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFunctions')
    protected async loadHogFunctions(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const loadedInvocations: CyclotronJobInvocationHogFunction[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFunction = await this.hogFunctionManager.getHogFunction(item.functionId)
                if (!hogFunction) {
                    logger.error('⚠️', 'Error finding hog function', {
                        id: item.functionId,
                    })
                    return null
                }

                if (!hogFunction.enabled || hogFunction.deleted) {
                    logger.info('⚠️', 'Skipping invocation due to hog function being deleted or disabled', {
                        id: item.functionId,
                    })
                    return null
                }

                loadedInvocations.push({
                    ...item,
                    state: item.state as CyclotronJobInvocationHogFunction['state'],
                    hogFunction,
                })
            })
        )

        return loadedInvocations
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        const invocationResults = await this.processInvocations(invocations)

        // NOTE: We queue results back for retries and async operations, then publish metrics in background
        const backgroundTask = this.queueInvocationResults(invocationResults).then(() => {
            // NOTE: After this point we parallelize and any issues are logged rather than thrown as retrying now would end up in duplicate messages
            return Promise.allSettled([
                this.hogFunctionMonitoringService
                    .queueInvocationResults(invocationResults)
                    .then(() => this.hogFunctionMonitoringService.flush())
                    .catch((err) => {
                        captureException(err)
                        logger.error('Error processing invocation results', { err })
                    }),
                this.hogWatcher.observeResults(invocationResults).catch((err: any) => {
                    captureException(err)
                    logger.error('Error observing results', { err })
                }),
            ])
        })

        return { backgroundTask, invocationResults }
    }

    protected async queueInvocationResults(invocations: CyclotronJobInvocationResult[]) {
        // Queue unfinished invocations back to the backfill topic for retries
        const unfinishedInvocations = invocations.filter((x) => !x.finished)

        if (unfinishedInvocations.length === 0 || !this.kafkaProducer) {
            return
        }

        await Promise.all(
            unfinishedInvocations.map(async (result) => {
                const invocation = result.invocation
                const serialized = serializeInvocation(invocation)

                const value = this.hub.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA
                    ? await compress(JSON.stringify(serialized))
                    : JSON.stringify(serialized)

                cdpJobSizeKb.observe(value.length / 1024)

                const headers: Record<string, string> = {
                    functionId: invocation.functionId,
                    teamId: invocation.teamId.toString(),
                }

                if (invocation.queueScheduledAt) {
                    headers.queueScheduledAt = invocation.queueScheduledAt.toString()
                }

                await this.kafkaProducer!.produce({
                    value: Buffer.from(value),
                    key: Buffer.from(invocation.id),
                    topic: this.topic,
                    headers,
                }).catch((e) => {
                    logger.error('🔄', 'Error producing backfill kafka message', {
                        error: String(e),
                        teamId: invocation.teamId,
                        functionId: invocation.functionId,
                        payloadSizeKb: value.length / 1024,
                    })

                    throw e
                })
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocations = await this.parseKafkaBatch(messages)
                const { backgroundTask, invocationResults } = await this.processBatch(invocations)

                return { backgroundTask, invocationResults }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('🔄', 'Stopping backfill consumer')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

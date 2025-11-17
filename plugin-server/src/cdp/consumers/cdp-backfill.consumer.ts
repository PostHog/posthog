import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_CDP_BACKFILL_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { isLegacyPluginHogFunction, isNativeHogFunction, isSegmentPluginHogFunction } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

export class CdpBackfillConsumer extends CdpConsumerBase {
    protected name = 'CdpBackfillConsumer'
    private kafkaConsumer: KafkaConsumer

    constructor(hub: Hub, topic: string = KAFKA_CDP_BACKFILL_EVENTS, groupId: string = 'cdp-backfill-consumer') {
        super(hub)
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

        logger.info('🔁', `${this.name} - handling batch`, {
            size: invocations.length,
        })

        const invocationResults = await this.processInvocations(invocations)

        // Queue results and publish metrics in background
        const backgroundTask = Promise.allSettled([
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

        return { backgroundTask, invocationResults }
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

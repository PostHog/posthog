import { captureException } from '@sentry/node'
import { Message } from 'node-rdkafka'

import { KAFKA_CDP_FUNCTION_CALLBACKS } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { status } from '../../utils/status'
import {
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionInvocationSerializedCompressed,
    HogFunctionTypeType,
    HogHooksFetchResponse,
} from '../types'
import { unGzipObject } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * This consumer only deals with kafka messages and will eventually be replaced by the Cyclotron worker
 */
export class CdpFunctionCallbackConsumer extends CdpConsumerBase {
    protected name = 'CdpFunctionCallbackConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination', 'internal_destination']

    public async processBatch(invocations: HogFunctionInvocation[]): Promise<void> {
        if (!invocations.length) {
            return
        }

        const invocationResults = await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeInvocations`,
            func: async () => {
                // NOTE: In the future this service will never do fetching (unless we decide we want to do it in node at some point)
                // This is just "for now" to support the transition to cyclotron
                const fetchQueue = invocations.filter((item) => item.queue === 'fetch')

                const fetchResults = await Promise.all(
                    fetchQueue.map((item) => {
                        return runInstrumentedFunction({
                            statsKey: `cdpConsumer.handleEachBatch.fetchExecutor.execute`,
                            func: () => this.fetchExecutor.execute(item),
                            timeout: 1000,
                        })
                    })
                )

                const hogQueue = invocations.filter((item) => item.queue === 'hog')
                const hogResults = await this.runManyWithHeartbeat(hogQueue, (item) => this.hogExecutor.execute(item))
                return [...hogResults, ...(fetchResults.filter(Boolean) as HogFunctionInvocationResult[])]
            },
        })

        await this.processInvocationResults(invocationResults)
        const newInvocations = invocationResults.filter((r) => !r.finished).map((r) => r.invocation)
        await this.queueInvocationsToKafka(newInvocations)
        await this.produceQueuedMessages()
    }

    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocation[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
                    // TRICKY: In the future we won't use kafka. For now though we need to parse messages as Cyclotron style jobs
                    // or hoghooks async callbacks

                    const invocations: HogFunctionInvocation[] = []

                    // Parse the base message value
                    const entries: (HogHooksFetchResponse | HogFunctionInvocationSerializedCompressed)[] = messages
                        .map((message) => {
                            try {
                                return JSON.parse(message.value!.toString())
                            } catch (e) {
                                status.error('Error parsing message', e)
                            }

                            return undefined
                        })
                        .filter(Boolean)

                    // Deserialize the compressed data
                    await Promise.all(
                        entries.map(async (item) => {
                            try {
                                const invocationSerialized = await unGzipObject<HogFunctionInvocationSerialized>(
                                    item.state
                                )

                                if ('asyncFunctionResponse' in item) {
                                    // This means it is a callback from hoghooks so we need to add the response to the invocation
                                    invocationSerialized.queue = 'hog'
                                    invocationSerialized.queueParameters = item.asyncFunctionResponse
                                }

                                const hogFunctionId =
                                    invocationSerialized.hogFunctionId ?? invocationSerialized.hogFunction?.id
                                const hogFunction = hogFunctionId
                                    ? this.hogFunctionManager.getHogFunction(hogFunctionId)
                                    : undefined

                                if (!hogFunction) {
                                    status.error('Error finding hog function', {
                                        id: invocationSerialized.hogFunctionId,
                                    })
                                    return
                                }

                                const invocation: HogFunctionInvocation = {
                                    ...invocationSerialized,
                                    hogFunction,
                                }

                                delete (invocation as any).hogFunctionId

                                invocations.push(invocation)
                            } catch (e) {
                                status.error('Error unzipping message', e, item.state)
                                captureException(e)
                            }
                        })
                    )

                    return invocations
                },
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()
        await this.startKafkaConsumer({
            topic: KAFKA_CDP_FUNCTION_CALLBACKS,
            groupId: 'cdp-function-callback-consumer',
            handleBatch: async (messages) => {
                const invocations = await this._parseKafkaBatch(messages)
                await this.processBatch(invocations)
            },
        })
    }
}

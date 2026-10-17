import { Message } from 'node-rdkafka'

import * as kafkaConsumerModule from '~/common/kafka/consumer'
import { KafkaConsumerInterface } from '~/common/kafka/consumer'
import { KafkaProducerWrapper, ProducerMessage } from '~/common/kafka/producer'

import { CdpConfig } from '../../config'
import { CyclotronJobQueueKafka } from '../../services/job-queue/job-queue-kafka'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'

type ConsumedBatchHandler = (messages: Message[]) => Promise<unknown>

export class KafkaQueueHandoff {
    private produced: Buffer[] = []
    private consumed: CyclotronJobInvocation[] = []
    private deliverBatch?: ConsumedBatchHandler

    private constructor(private jobQueue: CyclotronJobQueueKafka) {}

    static async start(
        config: Pick<CdpConfig, 'CDP_CYCLOTRON_COMPRESS_KAFKA_DATA' | 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'>
    ): Promise<KafkaQueueHandoff> {
        const handoff = new KafkaQueueHandoff(new CyclotronJobQueueKafka(undefined, config, 1))
        jest.spyOn(KafkaProducerWrapper, 'create').mockResolvedValue(handoff.fakeProducer())
        jest.spyOn(kafkaConsumerModule, 'createKafkaConsumer').mockReturnValue(handoff.fakeConsumer())
        await handoff.jobQueue.startAsProducer()
        await handoff.jobQueue.startAsConsumer('hog', (invocations) => {
            handoff.consumed.push(...invocations)
            return Promise.resolve({ backgroundTask: Promise.resolve() })
        })
        return handoff
    }

    async queue(invocations: CyclotronJobInvocation[]): Promise<Buffer[]> {
        return await this.capture(() => this.jobQueue.queueInvocations(invocations))
    }

    async requeue(results: CyclotronJobInvocationResult[]): Promise<Buffer[]> {
        return await this.capture(() => this.jobQueue.queueInvocationResults(results))
    }

    async consume(values: Buffer[]): Promise<CyclotronJobInvocation[]> {
        this.consumed = []
        await this.deliverBatch!(values.map((value) => ({ value }) as Message))
        return this.consumed
    }

    private async capture(produce: () => Promise<void>): Promise<Buffer[]> {
        this.produced = []
        await produce()
        return this.produced
    }

    private fakeProducer(): KafkaProducerWrapper {
        const produce = ({ value }: ProducerMessage): Promise<void> => {
            this.produced.push(value as Buffer)
            return Promise.resolve()
        }
        return { produce } as unknown as KafkaProducerWrapper
    }

    private fakeConsumer(): KafkaConsumerInterface {
        const connect = (eachBatch: ConsumedBatchHandler): Promise<void> => {
            this.deliverBatch = eachBatch
            return Promise.resolve()
        }
        return { connect } as unknown as KafkaConsumerInterface
    }
}

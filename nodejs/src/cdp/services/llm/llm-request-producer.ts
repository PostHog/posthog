import { KAFKA_CDP_LLM_REQUESTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { LlmStepRequest } from './llm-step.types'

// The seam the hogflow worker uses to hand an LLM request off to the executor fleet. An interface
// so tests assert "the worker dispatched request X" without a live Kafka.
export interface LlmRequestProducer {
    dispatch(request: LlmStepRequest): Promise<void>
}

export class KafkaLlmRequestProducer implements LlmRequestProducer {
    constructor(private kafkaProducer: KafkaProducerWrapper) {}

    public async dispatch(request: LlmStepRequest): Promise<void> {
        await this.kafkaProducer.produce({
            topic: KAFKA_CDP_LLM_REQUESTS,
            // Key by team so librdkafka's default partitioner keeps a team's requests on one
            // partition - per-team fairness and locality, per the RFC.
            key: String(request.teamId),
            value: Buffer.from(JSON.stringify(request)),
        })
    }
}

/**
 * gRPC Kafka Producer Client
 *
 * This client provides a lightweight interface to produce Kafka messages
 * via the Rust gRPC sidecar service instead of using node-rdkafka directly.
 *
 */
import { PromiseClient, createPromiseClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'

import { KafkaProducer } from '../proto/kafka_producer_connect'
import { ProduceRequest } from '../proto/kafka_producer_pb'

export interface GrpcKafkaProducerConfig {
    /** gRPC sidecar URL (e.g., "http://localhost:50051") */
    sidecarUrl: string
}

export type MessageValue = string | Buffer | Uint8Array
export type MessageKey = string | Buffer | Uint8Array | null

/**
 * Convert various message formats to Uint8Array
 */
function toUint8Array(value: MessageValue | MessageKey): Uint8Array | undefined {
    if (value === null || value === undefined) {
        return undefined
    }
    if (typeof value === 'string') {
        return new TextEncoder().encode(value)
    }
    if (Buffer.isBuffer(value)) {
        return new Uint8Array(value)
    }
    return value
}

/**
 * gRPC-based Kafka Producer Client
 *
 * This client connects to a Rust gRPC sidecar service that handles
 * Kafka message production. It provides a simple async interface
 * for producing messages.
 */
export class GrpcKafkaProducer {
    private client: PromiseClient<typeof KafkaProducer>

    constructor(config: GrpcKafkaProducerConfig) {
        const transport = createGrpcTransport({
            baseUrl: config.sidecarUrl,
            httpVersion: '2' as const,
        })

        this.client = createPromiseClient(KafkaProducer, transport)
    }

    /**
     * Produce a message to Kafka via the gRPC sidecar
     *
     * @param params Message parameters
     * @returns Promise resolving to the Kafka offset
     */
    async produce(params: {
        value: MessageValue
        key?: MessageKey
        topic: string
        headers?: Record<string, string>
    }): Promise<bigint> {
        const keyBytes = params.key !== undefined ? toUint8Array(params.key) : undefined

        const request = new ProduceRequest({
            value: toUint8Array(params.value)!,
            key: keyBytes,
            topic: params.topic,
            headers: params.headers || {},
        })

        const response = await this.client.produce(request)
        return response.offset
    }
}

/**
 * Create a gRPC Kafka producer client
 *
 * @param config Producer configuration
 * @returns GrpcKafkaProducer instance
 */
export function createGrpcKafkaProducer(config: GrpcKafkaProducerConfig): GrpcKafkaProducer {
    return new GrpcKafkaProducer(config)
}

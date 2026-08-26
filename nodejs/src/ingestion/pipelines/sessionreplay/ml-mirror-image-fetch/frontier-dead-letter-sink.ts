import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'

import { UrlDropReason } from './collected-urls-record'

export type FrontierDeadLetterReason = UrlDropReason | 'multiple'
type FrontierRecordVersion = '1' | '2' | 'unsupported' | 'unknown'

export interface FrontierDeadLetterSink {
    park(message: Message, reason: FrontierDeadLetterReason): Promise<void>
}

export class KafkaFrontierDeadLetterSink implements FrontierDeadLetterSink {
    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly topic: string
    ) {}

    public async park(message: Message, reason: FrontierDeadLetterReason): Promise<void> {
        await this.producer.produce({
            topic: this.topic,
            key: message.key ?? null,
            value: message.value,
            headers: {
                'dlq-reason': reason,
                'frontier-record-version': classifyFrontierRecordVersion(message.value),
                'source-topic': message.topic,
                'source-partition': String(message.partition),
                'source-offset': String(message.offset),
            },
        })
    }
}

function classifyFrontierRecordVersion(value: Buffer | null): FrontierRecordVersion {
    if (!value) {
        return 'unknown'
    }
    try {
        const parsed: unknown = parseJSON(value.toString())
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || !('v' in parsed)) {
            return 'unknown'
        }
        if (parsed.v === 1) {
            return '1'
        }
        if (parsed.v === 2) {
            return '2'
        }
        return 'unsupported'
    } catch {
        return 'unknown'
    }
}

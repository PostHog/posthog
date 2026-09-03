import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { MAX_RECORD_BYTES } from './collected-urls-record'
import { KafkaFrontierDeadLetterSink } from './frontier-dead-letter-sink'

describe('KafkaFrontierDeadLetterSink', () => {
    it('preserves the source key and value with bounded diagnostic headers', async () => {
        const produce = jest.fn(() => Promise.resolve())
        const sink = new KafkaFrontierDeadLetterSink({ produce } as unknown as KafkaProducerWrapper, 'frontier-dlq', [
            'frontier',
        ])
        const source = {
            topic: 'frontier',
            partition: 7,
            offset: 42,
            key: Buffer.from('example.com'),
            value: Buffer.from('{"v":2,"jobs":[]}'),
        } as Message

        await sink.park(source, 'bad_url')

        expect(produce).toHaveBeenCalledWith({
            topic: 'frontier-dlq',
            key: source.key,
            value: source.value,
            headers: {
                'dlq-reason': 'bad_url',
                'frontier-record-version': '2',
                'source-topic': 'frontier',
                'source-partition': '7',
                'source-offset': '42',
            },
        })
    })

    it('does not copy an unsupported version into a header', async () => {
        const produce = jest.fn(() => Promise.resolve())
        const sink = new KafkaFrontierDeadLetterSink({ produce } as unknown as KafkaProducerWrapper, 'frontier-dlq', [
            'frontier',
        ])

        await sink.park(
            {
                topic: 'frontier',
                partition: 0,
                offset: 1,
                key: null,
                value: Buffer.from('{"v":"private input"}'),
            } as Message,
            'unsupported_version'
        )

        expect(produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({ 'frontier-record-version': 'unsupported' }),
            })
        )
    })

    it('does not parse an oversized rejected value to classify its version', async () => {
        const produce = jest.fn(() => Promise.resolve())
        const sink = new KafkaFrontierDeadLetterSink({ produce } as unknown as KafkaProducerWrapper, 'frontier-dlq', [
            'frontier',
        ])

        await sink.park(
            {
                topic: 'frontier',
                partition: 0,
                offset: 1,
                key: null,
                value: Buffer.alloc(MAX_RECORD_BYTES + 1, '{'),
            } as Message,
            'oversized_record'
        )

        expect(produce).toHaveBeenCalledWith(
            expect.objectContaining({
                headers: expect.objectContaining({ 'frontier-record-version': 'unknown' }),
            })
        )
    })

    it('refuses a destination used by the image-fetch pipeline', () => {
        expect(
            () =>
                new KafkaFrontierDeadLetterSink({ produce: jest.fn() } as unknown as KafkaProducerWrapper, 'frontier', [
                    'frontier',
                ])
        ).toThrow('SESSION_RECORDING_ML_IMAGE_FETCH_DLQ_TOPIC')
    })
})

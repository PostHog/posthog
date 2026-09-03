import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { KafkaDeadLetterSink } from './dead-letter-sink'

describe('KafkaDeadLetterSink', () => {
    it('keeps transport headers beside the diagnostic headers', async () => {
        const produced: { headers?: Record<string, string> }[] = []
        const producer = {
            produce: (message: { headers?: Record<string, string> }) => {
                produced.push(message)
                return Promise.resolve()
            },
        } as unknown as KafkaProducerWrapper
        const sink = new KafkaDeadLetterSink(producer, 'image-scrub-dlq')

        await sink.park({
            ref: 'imageurl:team:hash',
            bytes: Buffer.from('compressed'),
            headers: { 'content-type': 'image/png', 'content-encoding': 'gzip' },
            detail: { reason: 'rejected', replayCount: 1 },
        })

        expect(produced[0].headers).toEqual({
            'content-type': 'image/png',
            'content-encoding': 'gzip',
            reason: 'rejected',
            replayCount: '1',
        })
    })
})

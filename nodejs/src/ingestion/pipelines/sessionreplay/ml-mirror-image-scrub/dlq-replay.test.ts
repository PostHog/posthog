import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { MAX_REPLAYS, replayBatch } from './dlq-replay'
import { REPLAY_COUNT_HEADER } from './image-batcher'

function parked(
    ref: string,
    bytes: string,
    replayCount?: number,
    transportHeaders: Record<string, string> = {}
): Message {
    return {
        topic: 'session_replay_image_scrub_dlq',
        partition: 0,
        offset: 0,
        key: Buffer.from(ref),
        value: Buffer.from(bytes),
        headers: [
            ...Object.entries(transportHeaders).map(([key, value]) => ({ [key]: Buffer.from(value) })),
            { reason: Buffer.from('rejected') },
            ...(replayCount === undefined ? [] : [{ [REPLAY_COUNT_HEADER]: Buffer.from(String(replayCount)) }]),
        ],
    } as unknown as Message
}

describe('replayBatch', () => {
    let produced: { topic: string; key: string; value: string; headers?: Record<string, string> }[]
    let producer: KafkaProducerWrapper

    beforeEach(() => {
        produced = []
        producer = {
            produce: (m: { topic: string; key: Buffer; value: Buffer; headers?: Record<string, string> }) => {
                produced.push({
                    topic: m.topic,
                    key: m.key.toString(),
                    value: m.value.toString(),
                    headers: m.headers,
                })
                return Promise.resolve()
            },
        } as unknown as KafkaProducerWrapper
    })

    it('returns the original bytes to the source topic under the same ref', async () => {
        const outcome = await replayBatch([parked('ref-1', 'original-image')], producer, 'session_replay_image_scrub')

        expect(outcome).toEqual({ replayed: 1, exhausted: 0 })
        expect(produced).toEqual([
            {
                topic: 'session_replay_image_scrub',
                key: 'ref-1',
                value: 'original-image',
                // The park's diagnostic headers describe an old failure and must not travel with a
                // fresh attempt. This inline image has no transport headers, so only the count survives.
                headers: { [REPLAY_COUNT_HEADER]: '1' },
            },
        ])
    })

    it('stops replaying an image that has already been round-tripped its limit', async () => {
        // A replay run is only worth making after the sidecar is fixed, and nothing enforces that.
        // Capping the trips means running it too early costs one wasted pass rather than an image
        // cycling between the two topics forever, spending scrub capacity on known-bad work.
        const outcome = await replayBatch(
            [parked('ref-1', 'poison', MAX_REPLAYS)],
            producer,
            'session_replay_image_scrub'
        )

        expect(outcome).toEqual({ replayed: 0, exhausted: 1 })
        // Left on the dead-letter topic, which holds the only copy of these bytes.
        expect(produced).toEqual([])
    })

    it('carries the count forward so trips accumulate across runs', async () => {
        await replayBatch([parked('ref-1', 'image', 1)], producer, 'session_replay_image_scrub')

        expect(produced[0].headers).toEqual({ [REPLAY_COUNT_HEADER]: '2' })
    })

    it('preserves the content headers needed to decode a replayed URL image', async () => {
        await replayBatch(
            [
                parked('ref-1', 'compressed-image', undefined, {
                    'content-type': 'image/png',
                    'content-encoding': 'gzip',
                }),
            ],
            producer,
            'session_replay_image_scrub'
        )

        expect(produced[0].headers).toEqual({
            'content-type': 'image/png',
            'content-encoding': 'gzip',
            [REPLAY_COUNT_HEADER]: '1',
        })
    })
})

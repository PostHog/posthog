import { TopicPartition } from 'kafkajs'

import {
    offsetHighWaterMarkKey,
    SessionOffsetHighWaterMark,
    SessionOffsetHighWaterMarks,
} from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-offset-high-water-mark'
import { Hub } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'

describe('session offset high-water mark', () => {
    jest.setTimeout(1000)
    let hub: Hub
    let closeHub: () => Promise<void>
    const keyPrefix = 'test-high-water-mark'
    let sessionOffsetHighWaterMark: SessionOffsetHighWaterMark

    async function deletePrefixedKeys() {
        const redisClient = await hub.redisPool.acquire()
        const keys = await redisClient.keys(`${keyPrefix}*`)
        const pipeline = redisClient.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
        await hub.redisPool.release(redisClient)
    }

    async function getWaterMarksFromRedis(tp: TopicPartition) {
        const client = await hub.redisPool.acquire()
        const key = offsetHighWaterMarkKey(keyPrefix, tp)
        const redisValue = await client.zrange(key, 0, -1, 'WITHSCORES')
        await hub.redisPool.release(client)

        return redisValue.reduce((acc: SessionOffsetHighWaterMarks, value: string, index: number) => {
            if (index % 2 === 0) {
                acc[value] = parseInt(redisValue[index + 1])
            }
            return acc
        }, {})
    }

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        sessionOffsetHighWaterMark = new SessionOffsetHighWaterMark(hub.redisPool, keyPrefix)
    })

    afterEach(async () => {
        await deletePrefixedKeys()
        await closeHub()
    })

    const expectMemoryAndRedisToEqual = async (tp: TopicPartition, toEqual: any) => {
        expect(await sessionOffsetHighWaterMark.getWaterMarks(tp)).toEqual(toEqual)
        expect(await getWaterMarksFromRedis(tp)).toEqual(toEqual)
    }

    describe('with no existing high-water marks', () => {
        it('can remove all high-water marks based on a given offset', async () => {
            await sessionOffsetHighWaterMark.onCommit({ topic: 'topic', partition: 1 }, 12)
            await expectMemoryAndRedisToEqual({ topic: 'topic', partition: 1 }, {})
        })

        it('can add a high-water mark', async () => {
            await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'some-session', 123)
            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 1 },
                {
                    'some-session': 123,
                }
            )
        })

        it('can get multiple watermarks without clashes', async () => {
            const results = await Promise.all([
                sessionOffsetHighWaterMark.getWaterMarks({ topic: 'topic', partition: 1 }),
                sessionOffsetHighWaterMark.getWaterMarks({ topic: 'topic', partition: 2 }),
            ])

            expect(results).toEqual([{}, {}])
        })

        it('can add multiple high-water marks in parallel', async () => {
            await Promise.all([
                sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'some-session', 10),
                sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'some-session2', 20),
                sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 2 }, 'some-session3', 30),
            ])

            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 1 },
                {
                    'some-session': 10,
                    'some-session2': 20,
                }
            )

            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 2 },
                {
                    'some-session3': 30,
                }
            )
        })
    })

    describe('with existing high-water marks', () => {
        beforeEach(async () => {
            // works even before anything is written to redis
            expect(await sessionOffsetHighWaterMark.getWaterMarks({ topic: 'topic', partition: 1 })).toStrictEqual({})

            await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'some-session', 123)
            await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 1 }, 'another-session', 12)
            await sessionOffsetHighWaterMark.add({ topic: 'topic', partition: 2 }, 'a-third-session', 1)
        })

        it('can get high-water marks for all sessions for a partition', async () => {
            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 1 },
                {
                    'some-session': 123,
                    'another-session': 12,
                }
            )
        })

        it('can remove all high-water marks based on a given offset', async () => {
            await sessionOffsetHighWaterMark.onCommit({ topic: 'topic', partition: 1 }, 12)

            // the commit updates redis
            // removes all high-water marks that are <= 12
            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 1 },
                {
                    'some-session': 123,
                }
            )
            // does not affect other partitions
            await expectMemoryAndRedisToEqual(
                { topic: 'topic', partition: 2 },
                {
                    'a-third-session': 1,
                }
            )
        })

        it('can check if an offset is below the high-water mark', async () => {
            const partitionOneTestCases: [number, boolean][] = [
                [124, false],
                [123, true],
                [12, true],
                [11, true],
                [1, true],
                [0, true],
            ]
            await Promise.allSettled(
                partitionOneTestCases.map(async ([offset, expected]) => {
                    expect(
                        await sessionOffsetHighWaterMark.isBelowHighWaterMark(
                            { topic: 'topic', partition: 1 },
                            'some-session',
                            offset
                        )
                    ).toBe(expected)
                })
            )
        })

        it('can check if an offset is below the high-water mark even if we have never seen it before', async () => {
            // there is nothing for a partition? we are always below the high-water mark
            expect(
                await sessionOffsetHighWaterMark.isBelowHighWaterMark(
                    { topic: 'topic', partition: 1 },
                    'anything we did not add yet',
                    5432
                )
            ).toBe(false)
        })
    })
})

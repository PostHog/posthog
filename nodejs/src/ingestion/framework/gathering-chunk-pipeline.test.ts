import { Message } from 'node-rdkafka'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { GatheringChunkPipeline } from './gathering-chunk-pipeline'
import { createContext, createNewChunkPipeline, createOkContext } from './helpers'
import { dlq, drop, ok, redirect } from './results'

const TEST_REDIRECT_OUTPUT = 'test_redirect' as const

// Scripted upstream: each next() runs the next entry, so tests control exactly
// how (and how fast) every pull resolves. Exhausted script → null.
class ScriptedChunkPipeline<T, C, R extends string = never> implements ChunkPipeline<T, T, C, C, R> {
    constructor(private script: Array<() => Promise<ChunkPipelineResultWithContext<T, C, R> | null>>) {}

    feed(_elements: OkResultWithContext<T, C>[]): void {}

    next(): Promise<ChunkPipelineResultWithContext<T, C, R> | null> {
        const entry = this.script.shift()
        return entry ? entry() : Promise.resolve(null)
    }
}

// Mock chunk processing pipeline for testing
class MockChunkProcessingPipeline<T, C, R extends string = never> implements ChunkPipeline<T, T, C, C, R> {
    private results: ChunkPipelineResultWithContext<T, C, R>[] = []
    private currentIndex = 0

    constructor(results: ChunkPipelineResultWithContext<T, C, R>[]) {
        this.results = results
    }

    feed(elements: OkResultWithContext<T, C>[]): void {
        this.results.push(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<T, C, R> | null> {
        if (this.currentIndex >= this.results.length) {
            return Promise.resolve(null)
        }
        return Promise.resolve(this.results[this.currentIndex++])
    }
}

describe('GatheringChunkPipeline', () => {
    let message1: Message
    let message2: Message
    let message3: Message
    let context1: { message: Message }
    let context2: { message: Message }
    let context3: { message: Message }

    beforeEach(() => {
        // Create different mock messages with unique properties
        message1 = {
            topic: 'test-topic',
            partition: 0,
            offset: 1,
            key: Buffer.from('key1'),
            value: Buffer.from('value1'),
            timestamp: Date.now(),
        } as Message

        message2 = {
            topic: 'test-topic',
            partition: 0,
            offset: 2,
            key: Buffer.from('key2'),
            value: Buffer.from('value2'),
            timestamp: Date.now() + 1,
        } as Message

        message3 = {
            topic: 'test-topic',
            partition: 0,
            offset: 3,
            key: Buffer.from('key3'),
            value: Buffer.from('value3'),
            timestamp: Date.now() + 2,
        } as Message

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
    })

    describe('constructor', () => {
        it('should create instance with sub-pipeline', () => {
            const subPipeline = createNewChunkPipeline<string>().build()
            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            expect(gatherPipeline).toBeInstanceOf(GatheringChunkPipeline)
        })
    })

    describe('feed', () => {
        it('should delegate to sub-pipeline', () => {
            const subPipeline = createNewChunkPipeline<string>().build()
            const spy = jest.spyOn(subPipeline, 'feed')
            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const testBatch = [createOkContext('test', context1)]

            gatherPipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when no results available', async () => {
            const subPipeline = createNewChunkPipeline<string>().build()
            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            expect(result).toBeNull()
        })

        it('should gather all results from sub-pipeline in single call', async () => {
            const subPipeline = new MockChunkProcessingPipeline([
                [createContext(ok('hello'), context1)],
                [createContext(ok('world'), context2)],
                [createContext(ok('test'), context3)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('hello'), context1),
                createContext(ok('world'), context2),
                createContext(ok('test'), context3),
            ])
            expect(result2).toBeNull()
        })

        it('should preserve non-success results', async () => {
            const dropResult = drop<string>('test drop')
            const dlqResult = dlq<string>('test dlq', new Error('test error'))
            const redirectResult = redirect('test redirect', TEST_REDIRECT_OUTPUT)

            const subPipeline = new MockChunkProcessingPipeline([
                [createContext(dropResult, context1)],
                [createContext(dlqResult, context2)],
                [createContext(redirectResult, context3)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(dropResult, context1),
                createContext(dlqResult, context2),
                createContext(redirectResult, context3),
            ])
            expect(result2).toBeNull()
        })

        it('should handle mixed success and non-success results', async () => {
            const dropResult = drop<string>('test drop')

            const subPipeline = new MockChunkProcessingPipeline([
                [createContext(ok('hello'), context1)],
                [createContext(dropResult, context2)],
                [createContext(ok('world'), context3)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('hello'), context1),
                createContext(dropResult, context2),
                createContext(ok('world'), context3),
            ])
            expect(result2).toBeNull()
        })

        it('should handle empty chunks from sub-pipeline', async () => {
            const subPipeline = new MockChunkProcessingPipeline([
                [], // Empty chunk
                [createContext(ok('hello'), context1)],
                [], // Another empty chunk
                [createContext(ok('world'), context2)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toEqual([createContext(ok('hello'), context1), createContext(ok('world'), context2)])
            expect(result2).toBeNull()
        })

        it('should return null when all chunks are empty', async () => {
            const subPipeline = new MockChunkProcessingPipeline([
                [], // Empty chunk
                [], // Another empty chunk
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            expect(result).toBeNull()
        })

        it('should preserve order of results from sub-pipeline', async () => {
            const subPipeline = new MockChunkProcessingPipeline([
                [createContext(ok('first'), context1)],
                [createContext(ok('second'), context2)],
                [createContext(ok('third'), context3)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()

            expect(result).toEqual([
                createContext(ok('first'), context1),
                createContext(ok('second'), context2),
                createContext(ok('third'), context3),
            ])
        })

        it('should handle large number of chunks', async () => {
            const chunks: ChunkPipelineResultWithContext<string, any>[] = []
            for (let i = 0; i < 10; i++) {
                chunks.push([createContext(ok(`item${i}`), context1)])
            }

            const subPipeline = new MockChunkProcessingPipeline(chunks)
            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            const result = await gatherPipeline.next()
            const result2 = await gatherPipeline.next()

            expect(result).toHaveLength(10)
            expect(result![0]).toEqual(createContext(ok('item0'), context1))
            expect(result![9]).toEqual(createContext(ok('item9'), context1))
            expect(result2).toBeNull()
        })

        it('barrier default: waits for a parked pull instead of emitting accumulated results', async () => {
            let release!: () => void
            const gate = new Promise<void>((resolve) => (release = resolve))

            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                () => Promise.resolve([createContext(ok('ready'), context1)]),
                () => gate.then(() => [createContext(ok('slow'), context2)]),
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            let settled = false
            const pending = gatherPipeline.next().then((result) => {
                settled = true
                return result
            })

            // Give the event loop several turns: a barrier gather must keep
            // waiting on the parked pull rather than emit 'ready' early.
            await new Promise((resolve) => setImmediate(resolve))
            await new Promise((resolve) => setImmediate(resolve))
            expect(settled).toBe(false)

            release()
            expect(await pending).toEqual([createContext(ok('ready'), context1), createContext(ok('slow'), context2)])
        })

        it('should resume after returning null when more batches are fed', async () => {
            const subPipeline = new MockChunkProcessingPipeline<string, { message: Message }>([
                [createContext(ok('first'), context1)],
                [createContext(ok('second'), context2)],
            ])

            const gatherPipeline = new GatheringChunkPipeline(subPipeline)

            // First round: process initial chunks
            const result1 = await gatherPipeline.next()
            expect(result1).toEqual([createContext(ok('first'), context1), createContext(ok('second'), context2)])

            // Should return null when exhausted
            const result2 = await gatherPipeline.next()
            expect(result2).toBeNull()

            // Feed more batches
            subPipeline.feed([createOkContext('third', context3)])

            // Should resume processing
            const result3 = await gatherPipeline.next()
            expect(result3).toEqual([createContext(ok('third'), context3)])

            // Should return null again
            const result4 = await gatherPipeline.next()
            expect(result4).toBeNull()
        })
    })

    describe('bounded mode (maxWaitMs / minItems)', () => {
        async function withWatchdog<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
            let timer: NodeJS.Timeout | undefined
            const timeout = new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new Error(`took longer than ${ms}ms: ${label}`)), ms)
            })
            try {
                return await Promise.race([promise, timeout])
            } finally {
                clearTimeout(timer)
            }
        }

        // Guards the "does bounding fragment chunks?" concern: pulls that keep
        // resolving (here through deliberately deep microtask chains) coalesce
        // into ONE chunk exactly like the barrier — the deadline never fires
        // because no pull is left in flight.
        it('coalesces resolving pulls into a single chunk, same as the barrier', async () => {
            const deepMicrotaskChunk =
                (value: string, context: { message: Message }) =>
                async (): Promise<ChunkPipelineResultWithContext<string, { message: Message }>> => {
                    for (let i = 0; i < 20; i++) {
                        await Promise.resolve()
                    }
                    return [createContext(ok(value), context)]
                }

            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                deepMicrotaskChunk('first', context1),
                deepMicrotaskChunk('second', context2),
                deepMicrotaskChunk('third', context3),
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline, { maxWaitMs: 5000 })

            const result = await withWatchdog(gatherPipeline.next(), 1500, 'coalescing must not wait for the deadline')

            expect(result).toEqual([
                createContext(ok('first'), context1),
                createContext(ok('second'), context2),
                createContext(ok('third'), context3),
            ])
            expect(await gatherPipeline.next()).toBeNull()
        })

        it('emits immediately when upstream reports empty — no deadline lingering (Kafka path stays latency-free)', async () => {
            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                () => Promise.resolve([createContext(ok('only'), context1)]),
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline, { maxWaitMs: 5000, minItems: 100 })

            // 1 < minItems and the deadline is far away, but upstream is empty:
            // waiting would only speculate on future feeds, so emit now.
            const result = await withWatchdog(gatherPipeline.next(), 1500, 'upstream-empty emission must not linger')
            expect(result).toEqual([createContext(ok('only'), context1)])
        })

        it('emits as soon as minItems accumulate, without touching further upstream pulls', async () => {
            let gatedPullStarted = false
            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                () => Promise.resolve([createContext(ok('one'), context1), createContext(ok('two'), context2)]),
                () => {
                    gatedPullStarted = true
                    return new Promise(() => {}) // would park forever
                },
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline, { maxWaitMs: 5000, minItems: 2 })

            const result = await withWatchdog(gatherPipeline.next(), 1500, 'minItems emission must not wait')
            expect(result).toEqual([createContext(ok('one'), context1), createContext(ok('two'), context2)])
            // minItems was satisfied before the next pull was issued.
            expect(gatedPullStarted).toBe(false)
        })

        it('below minItems: waits at most maxWaitMs on an in-flight pull, then emits and carries the pull without loss', async () => {
            let release!: () => void
            const gate = new Promise<void>((resolve) => (release = resolve))

            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                () => Promise.resolve([createContext(ok('ready'), context1)]),
                () => gate.then(() => [createContext(ok('slow'), context2)]),
                () => Promise.resolve([createContext(ok('after'), context3)]),
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline, { maxWaitMs: 25, minItems: 100 })

            // 'ready' is below minItems and the pull for 'slow' is parked: the
            // deadline (25ms) fires and 'ready' comes out — the parked pull is
            // neither awaited to completion nor abandoned.
            expect(await withWatchdog(gatherPipeline.next(), 1500, 'deadline emission')).toEqual([
                createContext(ok('ready'), context1),
            ])

            const second = gatherPipeline.next()
            release()
            // The carried-over pull delivers 'slow', and coalescing continues
            // with the now-ready 'after' chunk — nothing lost, nothing duplicated.
            expect(await second).toEqual([createContext(ok('slow'), context2), createContext(ok('after'), context3)])
            expect(await gatherPipeline.next()).toBeNull()
        })

        it('emits results accumulated before an upstream failure, then rejects permanently', async () => {
            const subPipeline = new ScriptedChunkPipeline<string, { message: Message }>([
                () => Promise.resolve([createContext(ok('done'), context1)]),
                () => Promise.reject(new Error('upstream boom')),
            ])
            const gatherPipeline = new GatheringChunkPipeline(subPipeline, { maxWaitMs: 25 })

            expect(await gatherPipeline.next()).toEqual([createContext(ok('done'), context1)])
            await expect(gatherPipeline.next()).rejects.toThrow('upstream boom')
            await expect(gatherPipeline.next()).rejects.toThrow('upstream boom')
        })
    })

    describe('builder guard', () => {
        it('rejects gather() directly following another gather()', () => {
            expect(() => createNewChunkPipeline<string>().gather().gather()).toThrow(
                'gather() cannot directly follow another gather()'
            )
        })
    })
})

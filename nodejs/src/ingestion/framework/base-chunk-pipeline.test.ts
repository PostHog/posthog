import { Message } from 'node-rdkafka'

import { createMockPipeline } from '~/tests/helpers/mock-pipeline'

import { BaseChunkPipeline } from './base-chunk-pipeline'
import { createBatch, createContext, createNewBatchPipeline, createOkContext } from './helpers'
import { dlq, drop, ok } from './results'

function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('test'),
        topic: 'test',
        partition: 0,
        offset: 1,
        key: Buffer.from('key1'),
        size: 4,
        timestamp: Date.now(),
        headers: [],
        ...overrides,
    }
}

describe('BaseChunkPipeline', () => {
    describe('basic functionality', () => {
        it('should process batch through pipeline', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), {
                    message: messages[0],
                    lastStep: 'anonymousChunkStep',
                }),
                createContext(ok({ processed: 'test2' }), {
                    message: messages[1],
                    lastStep: 'anonymousChunkStep',
                }),
            ])
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok(item)))
            }, rootPipeline)

            pipeline.feed([])
            const results = await pipeline.next()

            expect(results).toEqual(null)
        })
    })

    describe('batch operations', () => {
        it('should execute batch step on all successful values', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('2'), offset: 2 }),
                createTestMessage({ value: Buffer.from('3'), offset: 3 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => ok({ count: parseInt(item.message.value?.toString() || '0') * 2 }))
                )
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ count: 2 }), { message: messages[0], lastStep: 'anonymousChunkStep' }),
                createContext(ok({ count: 4 }), { message: messages[1], lastStep: 'anonymousChunkStep' }),
                createContext(ok({ count: 6 }), { message: messages[2], lastStep: 'anonymousChunkStep' }),
            ])
        })

        it('should preserve non-success results and only process successful ones', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('drop'), offset: 2 }),
                createTestMessage({ value: Buffer.from('3'), offset: 3 }),
                createTestMessage({ value: Buffer.from('dlq'), offset: 4 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const firstPipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => {
                        const value = item.message.value?.toString() || ''
                        if (value === 'drop') {
                            return drop('dropped item')
                        }
                        if (value === 'dlq') {
                            return dlq('dlq item', new Error('test error'))
                        }
                        return ok({ count: parseInt(value) })
                    })
                )
            }, rootPipeline)

            const secondPipeline = new BaseChunkPipeline((items: any[]) => {
                expect(items).toEqual([{ count: 1 }, { count: 3 }])
                return Promise.resolve(items.map((item: any) => ok({ count: item.count * 2 })))
            }, firstPipeline)

            secondPipeline.feed(batch)
            const results = await secondPipeline.next()

            expect(results).toEqual([
                createContext(ok({ count: 2 }), { message: messages[0], lastStep: 'anonymousChunkStep' }),
                createContext(drop('dropped item'), { message: messages[1], lastStep: 'anonymousChunkStep' }),
                createContext(ok({ count: 6 }), { message: messages[2], lastStep: 'anonymousChunkStep' }),
                createContext(dlq('dlq item', new Error('test error')), {
                    message: messages[3],
                    lastStep: 'anonymousChunkStep',
                }),
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from batch operations', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseChunkPipeline(() => {
                return Promise.reject(new Error('Batch step failed'))
            }, rootPipeline)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Batch step failed')
        })
    })

    describe('step name tracking', () => {
        it('should include step name in context for successful results', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            function testBatchStep(items: any[]) {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }

            const pipeline = new BaseChunkPipeline(testBatchStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), {
                    message: messages[0],
                    lastStep: 'testBatchStep',
                }),
                createContext(ok({ processed: 'test2' }), {
                    message: messages[1],
                    lastStep: 'testBatchStep',
                }),
            ])
        })

        it('should use anonymousChunkStep when step has no name', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const anonymousStep = (items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }

            const pipeline = new BaseChunkPipeline(anonymousStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), {
                    message: messages[0],
                    lastStep: 'anonymousStep',
                }),
            ])
        })

        it('should not update lastStep for failed results', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('drop'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            function testBatchStep(items: any[]) {
                return Promise.resolve(
                    items.map((item: any) => {
                        const value = item.message.value?.toString() || ''
                        if (value === 'drop') {
                            return drop('dropped item')
                        }
                        return ok({ processed: value })
                    })
                )
            }

            const pipeline = new BaseChunkPipeline(testBatchStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), {
                    message: messages[0],
                    lastStep: 'testBatchStep',
                }),
                createContext(drop('dropped item'), {
                    message: messages[1],
                    lastStep: 'testBatchStep',
                }),
            ])
        })
    })

    describe('side effects accumulation', () => {
        it('should accumulate side effects from previous context and current step result', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test'), offset: 1 })]

            const initialSideEffect1 = Promise.resolve('initial-side-effect-1')
            const initialSideEffect2 = Promise.resolve('initial-side-effect-2')
            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [initialSideEffect1, initialSideEffect2],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepSideEffect1 = Promise.resolve('step-side-effect-1')
            const stepSideEffect2 = Promise.resolve('step-side-effect-2')
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' }, [stepSideEffect1, stepSideEffect2])))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.sideEffects).toEqual([
                initialSideEffect1,
                initialSideEffect2,
                stepSideEffect1,
                stepSideEffect2,
            ])
        })

        it('should preserve context side effects when step returns no side effects', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test'), offset: 1 })]

            const existingSideEffect = Promise.resolve('existing-side-effect')
            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [existingSideEffect],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.sideEffects).toEqual([existingSideEffect])
        })

        it('should add step side effects when context has no existing side effects', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test'), offset: 1 })]

            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepSideEffect = Promise.resolve('step-side-effect')
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' }, [stepSideEffect])))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.sideEffects).toEqual([stepSideEffect])
        })

        it('should handle multiple items with different side effect patterns', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('item1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('item2'), offset: 2 }),
                createTestMessage({ value: Buffer.from('item3'), offset: 3 }),
            ]

            const sideEffect1 = Promise.resolve('context-1')
            const sideEffect2 = Promise.resolve('context-2')
            const sideEffect3 = Promise.resolve('context-3')

            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [sideEffect1],
                    }
                ),
                createOkContext(
                    { message: messages[1] },
                    {
                        message: messages[1],
                        sideEffects: [sideEffect2, sideEffect3],
                    }
                ),
                createOkContext(
                    { message: messages[2] },
                    {
                        message: messages[2],
                        sideEffects: [],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const step1SideEffect = Promise.resolve('step-1')
            const step3aSideEffect = Promise.resolve('step-3a')
            const step3bSideEffect = Promise.resolve('step-3b')
            const pipeline = new BaseChunkPipeline((_: any[]) => {
                return Promise.resolve([
                    ok({ processed: 'result1' }, [step1SideEffect]),
                    ok({ processed: 'result2' }), // No step side effects
                    ok({ processed: 'result3' }, [step3aSideEffect, step3bSideEffect]),
                ])
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(3)

            // First item: context + step side effects
            expect(results![0].context.sideEffects).toEqual([sideEffect1, step1SideEffect])

            // Second item: only context side effects (step has none)
            expect(results![1].context.sideEffects).toEqual([sideEffect2, sideEffect3])

            // Third item: only step side effects (context has none)
            expect(results![2].context.sideEffects).toEqual([step3aSideEffect, step3bSideEffect])
        })
    })

    describe('warning accumulation', () => {
        it('should accumulate warnings from step results', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const stepWarning = { type: 'merge_race_condition' as const, details: { message: 'step warning' } }
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' }, [], [stepWarning])))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.warnings).toEqual([stepWarning])
        })

        it('should merge context warnings with step warnings', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const contextWarning = { type: 'client_ingestion_warning' as const, details: { message: 'from context' } }
            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [],
                        warnings: [contextWarning],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepWarning = { type: 'schema_validation_failed' as const, details: { message: 'from step' } }
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' }, [], [stepWarning])))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.warnings).toEqual([contextWarning, stepWarning])
        })

        it('should handle multiple warnings from multiple items', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('item1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('item2'), offset: 2 }),
                createTestMessage({ value: Buffer.from('item3'), offset: 3 }),
            ]

            const contextWarning1 = { type: 'ignored_invalid_timestamp' as const, details: { idx: 1 } }
            const contextWarning2 = { type: 'invalid_heatmap_data' as const, details: { idx: 2 } }

            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [],
                        warnings: [contextWarning1],
                    }
                ),
                createOkContext(
                    { message: messages[1] },
                    {
                        message: messages[1],
                        sideEffects: [],
                        warnings: [contextWarning2],
                    }
                ),
                createOkContext(
                    { message: messages[2] },
                    {
                        message: messages[2],
                        sideEffects: [],
                        warnings: [],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepWarning1 = { type: 'message_size_too_large' as const, details: { result: 1 } }
            const stepWarning3a = { type: 'group_key_too_long' as const, details: { result: 3 } }
            const stepWarning3b = { type: 'event_dropped_too_old' as const, details: { result: 3 } }
            const pipeline = new BaseChunkPipeline((_: any[]) => {
                return Promise.resolve([
                    ok({ processed: 'result1' }, [], [stepWarning1]),
                    ok({ processed: 'result2' }), // No step warnings
                    ok({ processed: 'result3' }, [], [stepWarning3a, stepWarning3b]),
                ])
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(3)

            // First item: context + step warnings
            expect(results![0].context.warnings).toEqual([contextWarning1, stepWarning1])

            // Second item: only context warnings (step has none)
            expect(results![1].context.warnings).toEqual([contextWarning2])

            // Third item: only step warnings (context has none)
            expect(results![2].context.warnings).toEqual([stepWarning3a, stepWarning3b])
        })

        it('should preserve warnings for non-success results', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('drop'), offset: 2 }),
            ]

            const contextWarning = { type: 'client_ingestion_warning' as const, details: { message: 'existing' } }
            const batch = [
                createOkContext(
                    { message: messages[0] },
                    {
                        message: messages[0],
                        sideEffects: [],
                        warnings: [contextWarning],
                    }
                ),
                createContext(drop('drop_reason'), {
                    message: messages[1],
                    sideEffects: [],
                    warnings: [contextWarning],
                }),
            ]

            const mockPrevious = createMockPipeline(batch)
            const pipeline = new BaseChunkPipeline((items: any[]) => {
                // Only process OK results
                return Promise.resolve(items.map(() => ok({ processed: 'result' })))
            }, mockPrevious)

            const results = await pipeline.next()

            expect(results).toHaveLength(2)

            // OK result should have warnings accumulated
            expect(results![0].context.warnings).toEqual([contextWarning])

            // Drop result should preserve context warnings
            expect(results![1].context.warnings).toEqual([contextWarning])
        })
    })
})

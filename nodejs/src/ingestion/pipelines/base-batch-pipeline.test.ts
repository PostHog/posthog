import { Message } from 'node-rdkafka'

import { BaseBatchPipeline } from './base-batch-pipeline'
import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { DefaultContext, createBatch, createContext, createNewBatchPipeline } from './helpers'
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

describe('BaseBatchPipeline', () => {
    describe('basic functionality', () => {
        it('should process batch through pipeline', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ processed: 'test1' }), {
                    message: messages[0],
                    lastStep: 'anonymousBatchStep',
                }),
                createContext(ok({ processed: 'test2' }), {
                    message: messages[1],
                    lastStep: 'anonymousBatchStep',
                }),
            ])
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
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
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => ok({ count: parseInt(item.message.value?.toString() || '0') * 2 }))
                )
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                createContext(ok({ count: 2 }), { message: messages[0], lastStep: 'anonymousBatchStep' }),
                createContext(ok({ count: 4 }), { message: messages[1], lastStep: 'anonymousBatchStep' }),
                createContext(ok({ count: 6 }), { message: messages[2], lastStep: 'anonymousBatchStep' }),
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
            const firstPipeline = new BaseBatchPipeline((items: any[]) => {
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

            const secondPipeline = new BaseBatchPipeline((items: any[]) => {
                expect(items).toEqual([{ count: 1 }, { count: 3 }])
                return Promise.resolve(items.map((item: any) => ok({ count: item.count * 2 })))
            }, firstPipeline)

            secondPipeline.feed(batch)
            const results = await secondPipeline.next()

            expect(results).toEqual([
                createContext(ok({ count: 2 }), { message: messages[0], lastStep: 'anonymousBatchStep' }),
                createContext(drop('dropped item'), { message: messages[1], lastStep: 'anonymousBatchStep' }),
                createContext(ok({ count: 6 }), { message: messages[2], lastStep: 'anonymousBatchStep' }),
                createContext(dlq('dlq item', new Error('test error')), {
                    message: messages[3],
                    lastStep: 'anonymousBatchStep',
                }),
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from batch operations', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseBatchPipeline(() => {
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

            const pipeline = new BaseBatchPipeline(testBatchStep, rootPipeline)

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

        it('should use anonymousBatchStep when step has no name', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const anonymousStep = (items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }

            const pipeline = new BaseBatchPipeline(anonymousStep, rootPipeline)

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

            const pipeline = new BaseBatchPipeline(testBatchStep, rootPipeline)

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
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [initialSideEffect1, initialSideEffect2],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepSideEffect1 = Promise.resolve('step-side-effect-1')
            const stepSideEffect2 = Promise.resolve('step-side-effect-2')
            const pipeline = new BaseBatchPipeline((items: any[]) => {
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
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [existingSideEffect],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
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
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepSideEffect = Promise.resolve('step-side-effect')
            const pipeline = new BaseBatchPipeline((items: any[]) => {
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
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [sideEffect1],
                }),
                createContext(ok({ message: messages[1] }), {
                    message: messages[1],
                    sideEffects: [sideEffect2, sideEffect3],
                }),
                createContext(ok({ message: messages[2] }), {
                    message: messages[2],
                    sideEffects: [],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const step1SideEffect = Promise.resolve('step-1')
            const step3aSideEffect = Promise.resolve('step-3a')
            const step3bSideEffect = Promise.resolve('step-3b')
            const pipeline = new BaseBatchPipeline((_: any[]) => {
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

            const stepWarning = { type: 'test_warning', details: { message: 'step warning' } }
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map(() => ok({ processed: 'result' }, [], [stepWarning])))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.warnings).toEqual([stepWarning])
        })

        it('should merge context warnings with step warnings', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const contextWarning = { type: 'context_warning', details: { message: 'from context' } }
            const batch = [
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [],
                    warnings: [contextWarning],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepWarning = { type: 'step_warning', details: { message: 'from step' } }
            const pipeline = new BaseBatchPipeline((items: any[]) => {
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

            const contextWarning1 = { type: 'context_warning_1', details: { idx: 1 } }
            const contextWarning2 = { type: 'context_warning_2', details: { idx: 2 } }

            const batch = [
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [],
                    warnings: [contextWarning1],
                }),
                createContext(ok({ message: messages[1] }), {
                    message: messages[1],
                    sideEffects: [],
                    warnings: [contextWarning2],
                }),
                createContext(ok({ message: messages[2] }), {
                    message: messages[2],
                    sideEffects: [],
                    warnings: [],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()

            const stepWarning1 = { type: 'step_warning_1', details: { result: 1 } }
            const stepWarning3a = { type: 'step_warning_3a', details: { result: 3 } }
            const stepWarning3b = { type: 'step_warning_3b', details: { result: 3 } }
            const pipeline = new BaseBatchPipeline((_: any[]) => {
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

            const contextWarning = { type: 'context_warning', details: { message: 'existing' } }
            const batch: BatchPipelineResultWithContext<{ message: Message }, DefaultContext> = [
                createContext(ok({ message: messages[0] }), {
                    message: messages[0],
                    sideEffects: [],
                    warnings: [contextWarning],
                }),
                createContext(drop('drop_reason'), {
                    message: messages[1],
                    sideEffects: [],
                    warnings: [contextWarning],
                }),
            ]

            const rootPipeline = createNewBatchPipeline().build()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                // Only process OK results
                return Promise.resolve(items.map(() => ok({ processed: 'result' })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(2)

            // OK result should have warnings accumulated
            expect(results![0].context.warnings).toEqual([contextWarning])

            // Drop result should preserve context warnings
            expect(results![1].context.warnings).toEqual([contextWarning])
        })
    })
})

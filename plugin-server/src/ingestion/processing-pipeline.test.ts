import { Message } from 'node-rdkafka'

import { drop, success } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { createNewPipeline } from './pipeline-types'
import { ProcessingPipeline } from './processing-pipeline'

describe('ProcessingPipeline', () => {
    describe('basic functionality', () => {
        it('should process single item through pipeline', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline().pipe((input) => {
                return success({ processed: input.message.value?.toString() })
            })

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: success({ processed: 'test' }), context: { message } })
        })

        it('should create pipeline with success result using create()', async () => {
            const message: Message = { value: Buffer.from('data'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = ProcessingPipeline.create<{ message: Message }>()

            const result = await pipeline.process({ result: success({ message }), context: { message } })
            expect(result).toEqual({ result: success({ message }), context: { message } })
        })
    })

    describe('pipe() - synchronous steps', () => {
        it('should execute step when result is success', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline().pipe((input) => {
                return success({ count: parseInt(input.message.value?.toString() || '0') + 1 })
            })

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: success({ count: 2 }), context: { message } })
        })

        it('should skip step when result is drop', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const secondStep = jest.fn((input) => {
                return success({ count: parseInt(input.message.value?.toString() || '0') + 1 })
            })

            const pipeline = createNewPipeline()
                .pipe(() => {
                    return drop('dropped by first step')
                })
                .pipe(secondStep)

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: drop('dropped by first step'), context: { message } })
            expect(secondStep).not.toHaveBeenCalled()
        })

        it('should chain multiple synchronous steps', async () => {
            const message: Message = { value: Buffer.from('0'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline()
                .pipe((input) => {
                    return success({ count: parseInt(input.message.value?.toString() || '0') + 1 })
                })
                .pipe((input) => {
                    return success({ count: input.count, doubled: input.count * 2 })
                })
                .pipe((input) => {
                    return success({ final: `count: ${input.count}, doubled: ${input.doubled}` })
                })

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: success({ final: 'count: 1, doubled: 2' }), context: { message } })
        })

        it('should stop chain when step returns drop', async () => {
            const message: Message = { value: Buffer.from('0'), topic: 'test', partition: 0, offset: 1 } as Message

            const step3 = jest.fn((input) => {
                return success({ final: `count: ${input.count}` })
            })

            const pipeline = createNewPipeline()
                .pipe((input) => {
                    return success({ count: parseInt(input.message.value?.toString() || '0') + 1 })
                })
                .pipe(() => {
                    return drop('step2 dropped')
                })
                .pipe(step3)

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: drop('step2 dropped'), context: { message } })
        })
    })

    describe('pipeAsync() - mixed sync/async steps', () => {
        it('should execute async steps', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline().pipeAsync(async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: parseInt(input.message.value?.toString() || '0') + 1 })
            })

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: success({ count: 2 }), context: { message } })
        })

        it('should not execute async step when result is failure', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const asyncStep = jest.fn(async () => {
                await Promise.resolve()
                return success({ executed: true })
            })

            const pipeline = createNewPipeline()
                .pipe(() => {
                    return drop('initial drop')
                })
                .pipeAsync(asyncStep)

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: drop('initial drop'), context: { message } })
            expect(asyncStep).not.toHaveBeenCalled()
        })
    })

    describe('error handling', () => {
        it('should handle async step that throws an error', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline().pipeAsync(async () => {
                await Promise.resolve()
                throw new Error('Step failed')
            })

            await expect(pipeline.process({ result: success({ message }), context: { message } })).rejects.toThrow(
                'Step failed'
            )
        })

        it('should handle sync step that throws an error', async () => {
            const message: Message = { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline().pipe(() => {
                throw new Error('Sync step failed')
            })

            await expect(pipeline.process({ result: success({ message }), context: { message } })).rejects.toThrow(
                'Sync step failed'
            )
        })
    })

    describe('type safety and generics', () => {
        it('should maintain type safety through pipeline transformations', async () => {
            const message: Message = { value: Buffer.from('42'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = createNewPipeline()
                .pipe((input) => {
                    const a = parseInt(input.message.value?.toString() || '0')
                    expect(typeof a).toBe('number')
                    return success({ b: a.toString() })
                })
                .pipe((input) => {
                    expect(typeof input.b).toBe('string')
                    return success({ c: input.b === '42' })
                })

            const result = await pipeline.process({ result: success({ message }), context: { message } })

            expect(result).toEqual({ result: success({ c: true }), context: { message } })
        })
    })
})

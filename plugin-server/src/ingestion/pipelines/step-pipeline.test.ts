import { Message } from 'node-rdkafka'

import { drop, isOkResult, ok } from './results'
import { StartPipeline } from './start-pipeline'
import { StepPipeline } from './step-pipeline'

describe('StepPipeline', () => {
    describe('constructor', () => {
        it('should create instance with step and previous pipeline', () => {
            const mockStep = jest.fn()
            const mockPrevious = {} as any

            const pipeline = new StepPipeline(mockStep, mockPrevious)

            expect(pipeline).toBeInstanceOf(StepPipeline)
        })
    })

    describe('process', () => {
        it('should execute step when previous result is success', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn().mockResolvedValue(ok({ processed: 'test' }))
            const previous = new StartPipeline<{ data: string }>()

            const pipeline = new StepPipeline(step, previous)
            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })

            expect(step).toHaveBeenCalledWith({ data: 'test' })
            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: { message, lastStep: 'mockConstructor' },
            })
        })

        it('should skip step when previous result is not success', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn()
            const previous = new StartPipeline<{ data: string }>()

            const pipeline = new StepPipeline(step, previous)
            const result = await pipeline.process({ result: drop('dropped'), context: { message } })

            expect(step).not.toHaveBeenCalled()
            expect(result).toEqual({ result: drop('dropped'), context: { message } })
        })

        it('should handle step errors', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn().mockRejectedValue(new Error('Step failed'))
            const previous = new StartPipeline<{ data: string }>()

            const pipeline = new StepPipeline(step, previous)

            await expect(pipeline.process({ result: ok({ data: 'test' }), context: { message } })).rejects.toThrow(
                'Step failed'
            )
        })
    })

    describe('pipe', () => {
        it('should create new StepPipeline with async step', () => {
            const step1 = jest.fn()
            const step = jest.fn()
            const previous = {} as any

            const pipeline1 = new StepPipeline(step1, previous)
            const pipeline2 = pipeline1.pipe(step)

            expect(pipeline2).toBeInstanceOf(StepPipeline)
        })

        it('should execute steps in order when processing through chained async pipeline', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step1 = jest.fn().mockImplementation((input) => {
                return Promise.resolve(ok({ value: input.value * 3 })) // Multiply by 3
            })
            const step = jest.fn().mockImplementation(async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return ok({ value: input.value - 2 }) // Subtract 2
            })
            const previous = new StartPipeline<{ value: number }>()

            const pipeline1 = new StepPipeline(step1, previous)
            const pipeline2 = pipeline1.pipe(step)

            const result = await pipeline2.process({ result: ok({ value: 4 }), context: { message } })

            expect(step1).toHaveBeenCalledWith({ value: 4 })
            expect(step).toHaveBeenCalledWith({ value: 12 }) // 4 * 3
            const pipelineResult = result.result
            expect(isOkResult(pipelineResult)).toBe(true)
            if (isOkResult(pipelineResult)) {
                expect(pipelineResult.value).toEqual({ value: 10 }) // (4 * 3) - 2 = 10
            }
            expect(step1).toHaveBeenCalledTimes(1)
            expect(step).toHaveBeenCalledTimes(1)
        })
    })

    describe('step name tracking', () => {
        it('should include step name in context for successful results', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            function testStep(input: any) {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })

            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: { message, lastStep: 'testStep' },
            })
        })

        it('should use anonymousStep when step has no name', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const anonymousStep = (input: any) => {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }>()
            const pipeline = new StepPipeline(anonymousStep, previous)
            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })

            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: { message, lastStep: 'anonymousStep' },
            })
        })

        it('should not update lastStep for failed results', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            function testStep(input: any) {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process({ result: drop('dropped'), context: { message } })

            expect(result).toEqual({
                result: drop('dropped'),
                context: { message }, // No lastStep update for failed results
            })
        })

        it('should preserve existing lastStep in context', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            function testStep(input: any) {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process({
                result: ok({ data: 'test' }),
                context: { message, lastStep: 'firstStep' },
            })

            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: { message, lastStep: 'testStep' }, // Should update to current step
            })
        })
    })
})

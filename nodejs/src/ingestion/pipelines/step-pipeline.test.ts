import { Message } from 'node-rdkafka'

import { createContext } from './helpers'
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
            const previous = new StartPipeline<{ data: string }, unknown>()

            const pipeline = new StepPipeline(step, previous)
            const result = await pipeline.process(createContext(ok({ data: 'test' }), { message }))

            expect(step).toHaveBeenCalledWith({ data: 'test' })
            expect(result).toEqual(createContext(ok({ processed: 'test' }), { message, lastStep: 'mockConstructor' }))
        })

        it('should skip step when previous result is not success', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn()
            const previous = new StartPipeline<{ data: string }, unknown>()

            const pipeline = new StepPipeline(step, previous)
            const result = await pipeline.process(createContext(drop('dropped'), { message }))

            expect(step).not.toHaveBeenCalled()
            expect(result).toEqual(createContext(drop('dropped'), { message }))
        })

        it('should handle step errors', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn().mockRejectedValue(new Error('Step failed'))
            const previous = new StartPipeline<{ data: string }, unknown>()

            const pipeline = new StepPipeline(step, previous)

            await expect(pipeline.process(createContext(ok({ data: 'test' }), { message }))).rejects.toThrow(
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
            const previous = new StartPipeline<{ value: number }, unknown>()

            const pipeline1 = new StepPipeline(step1, previous)
            const pipeline2 = pipeline1.pipe(step)

            const result = await pipeline2.process(createContext(ok({ value: 4 }), { message }))

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

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process(createContext(ok({ data: 'test' }), { message }))

            expect(result).toEqual(createContext(ok({ processed: 'test' }), { message, lastStep: 'testStep' }))
        })

        it('should use anonymousStep when step has no name', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const anonymousStep = (input: any) => {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(anonymousStep, previous)
            const result = await pipeline.process(createContext(ok({ data: 'test' }), { message }))

            expect(result).toEqual(createContext(ok({ processed: 'test' }), { message, lastStep: 'anonymousStep' }))
        })

        it('should not update lastStep for failed results', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            function testStep(input: any) {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process(createContext(drop('dropped'), { message }))

            expect(result).toEqual(
                createContext(drop('dropped'), { message }) // No lastStep update for failed results
            )
        })

        it('should preserve existing lastStep in context', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            function testStep(input: any) {
                return Promise.resolve(ok({ processed: input.data }))
            }

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(testStep, previous)
            const result = await pipeline.process(
                createContext(ok({ data: 'test' }), { message, lastStep: 'firstStep' })
            )

            expect(result).toEqual(
                createContext(ok({ processed: 'test' }), { message, lastStep: 'testStep' }) // Should update to current step
            )
        })
    })

    describe('side effects accumulation', () => {
        it('should accumulate side effects from previous context and current step result', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            // Create initial context with some side effects
            const initialSideEffect1 = Promise.resolve('initial-side-effect-1')
            const initialSideEffect2 = Promise.resolve('initial-side-effect-2')

            // Step that adds its own side effects
            const stepSideEffect1 = Promise.resolve('step-side-effect-1')
            const stepSideEffect2 = Promise.resolve('step-side-effect-2')
            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [stepSideEffect1, stepSideEffect2]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), {
                message,
                sideEffects: [initialSideEffect1, initialSideEffect2],
            })

            const result = await pipeline.process(input)

            expect(result.context.sideEffects).toEqual([
                initialSideEffect1,
                initialSideEffect2,
                stepSideEffect1,
                stepSideEffect2,
            ])
        })

        it('should preserve context side effects when step returns no side effects', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const existingSideEffect = Promise.resolve('existing-side-effect')
            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' })) // No side effects

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), { message, sideEffects: [existingSideEffect] })

            const result = await pipeline.process(input)

            expect(result.context.sideEffects).toEqual([existingSideEffect])
        })

        it('should add step side effects when context has no existing side effects', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const stepSideEffect = Promise.resolve('step-side-effect')
            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [stepSideEffect]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), { message })

            const result = await pipeline.process(input)

            expect(result.context.sideEffects).toEqual([stepSideEffect])
        })

        it('should not modify side effects for non-successful results', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const existingSideEffect = Promise.resolve('existing-side-effect')
            const step = jest.fn() // Should not be called

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(drop<{ data: string }>('dropped'), {
                message,
                sideEffects: [existingSideEffect],
            })

            const result = await pipeline.process(input)

            expect(step).not.toHaveBeenCalled()
            expect(result.context.sideEffects).toEqual([existingSideEffect])
            expect(result.result).toEqual(drop('dropped'))
        })

        it('should accumulate side effects across multiple chained steps', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const initialSideEffect = Promise.resolve('initial')
            const step1SideEffect = Promise.resolve('step1')
            const step2SideEffect = Promise.resolve('step2')

            const step1 = jest.fn().mockResolvedValue(ok({ value: 'processed1' }, [step1SideEffect]))
            const step2 = jest.fn().mockResolvedValue(ok({ value: 'processed2' }, [step2SideEffect]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline1 = new StepPipeline(step1, previous)
            const pipeline2 = new StepPipeline(step2, pipeline1)

            const input = createContext(ok({ data: 'test' }), { message, sideEffects: [initialSideEffect] })

            const result = await pipeline2.process(input)

            expect(result.context.sideEffects).toEqual([initialSideEffect, step1SideEffect, step2SideEffect])
        })

        it('should handle empty side effects arrays correctly', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [])) // Empty side effects array

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), { message })

            const result = await pipeline.process(input)

            expect(result.context.sideEffects).toEqual([])
        })

        it('should preserve order of side effects', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const contextSideEffect1 = Promise.resolve('context-1')
            const contextSideEffect2 = Promise.resolve('context-2')
            const stepSideEffect1 = Promise.resolve('step-1')
            const stepSideEffect2 = Promise.resolve('step-2')

            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [stepSideEffect1, stepSideEffect2]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), {
                message,
                sideEffects: [contextSideEffect1, contextSideEffect2],
            })

            const result = await pipeline.process(input)

            // Should preserve order: context side effects first, then step side effects
            expect(result.context.sideEffects).toEqual([
                contextSideEffect1,
                contextSideEffect2,
                stepSideEffect1,
                stepSideEffect2,
            ])
        })
    })

    describe('warning accumulation', () => {
        it('should accumulate warnings from step results', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const stepWarning = { type: 'test_warning', details: { message: 'from step' } }
            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [], [stepWarning]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), { message })
            const result = await pipeline.process(input)

            expect(result.context.warnings).toEqual([stepWarning])
        })

        it('should merge context warnings with step warnings', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const contextWarning = { type: 'context_warning', details: { message: 'from context' } }
            const stepWarning = { type: 'step_warning', details: { message: 'from step' } }

            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [], [stepWarning]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), {
                message,
                warnings: [contextWarning],
            })
            const result = await pipeline.process(input)

            expect(result.context.warnings).toEqual([contextWarning, stepWarning])
        })

        it('should handle empty warnings arrays', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), { message })
            const result = await pipeline.process(input)

            expect(result.context.warnings).toEqual([])
        })

        it('should preserve order of warnings', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const contextWarning1 = { type: 'context_warning_1', details: { idx: 1 } }
            const contextWarning2 = { type: 'context_warning_2', details: { idx: 2 } }
            const stepWarning1 = { type: 'step_warning_1', details: { idx: 3 } }
            const stepWarning2 = { type: 'step_warning_2', details: { idx: 4 } }

            const step = jest.fn().mockResolvedValue(ok({ processed: 'result' }, [], [stepWarning1, stepWarning2]))

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext(ok({ data: 'test' }), {
                message,
                warnings: [contextWarning1, contextWarning2],
            })
            const result = await pipeline.process(input)

            // Should preserve order: context warnings first, then step warnings
            expect(result.context.warnings).toEqual([contextWarning1, contextWarning2, stepWarning1, stepWarning2])
        })

        it('should not accumulate warnings when step is skipped (non-OK result)', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const contextWarning = { type: 'context_warning', details: { message: 'from context' } }
            const step = jest.fn()

            const previous = new StartPipeline<{ data: string }, unknown>()
            const pipeline = new StepPipeline(step, previous)

            const input = createContext<{ data: string }, { message: Message }>(drop('dropped'), {
                message,
                warnings: [contextWarning],
            })
            const result = await pipeline.process(input)

            // Should preserve context warnings but not call step
            expect(step).not.toHaveBeenCalled()
            expect(result.context.warnings).toEqual([contextWarning])
        })
    })
})

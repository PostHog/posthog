import { dlq, drop, redirect, success } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import {
    AsyncPreprocessingStep,
    AsyncProcessingPipeline,
    ProcessingPipeline,
    SyncPreprocessingStep,
} from './processing-pipeline'

describe('ProcessingPipeline', () => {
    describe('static methods', () => {
        it('should create pipeline with success result using of()', () => {
            const value = { test: 'data' }
            const pipeline = ProcessingPipeline.of(value)

            const result = pipeline.unwrap()
            expect(result).toEqual(success(value))
        })
    })

    describe('pipe() - synchronous steps', () => {
        it('should execute step when result is success', () => {
            const initialValue = { count: 1 }
            const step: SyncPreprocessingStep<typeof initialValue, { count: number }> = (input) => {
                return success({ count: input.count + 1 })
            }

            const result = ProcessingPipeline.of(initialValue).pipe(step).unwrap()

            expect(result).toEqual(success({ count: 2 }))
        })

        it('should skip step when result is drop', () => {
            const initialValue = { count: 1 }
            const dropStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return drop('dropped by first step')
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = ProcessingPipeline.of(initialValue).pipe(dropStep).pipe(secondStep).unwrap()

            expect(result).toEqual(drop('dropped by first step'))
            expect(secondStep).not.toHaveBeenCalled()
        })

        it('should skip step when result is redirect', () => {
            const initialValue = { count: 1 }
            const redirectStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return redirect('test redirect', 'overflow-topic', true, false)
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = ProcessingPipeline.of(initialValue).pipe(redirectStep).pipe(secondStep).unwrap()

            expect(result).toEqual(redirect('test redirect', 'overflow-topic', true, false))
            expect(secondStep).not.toHaveBeenCalled()
        })

        it('should skip step when result is dlq', () => {
            const initialValue = { count: 1 }
            const dlqStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return dlq('test dlq', new Error('test error'))
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = ProcessingPipeline.of(initialValue).pipe(dlqStep).pipe(secondStep).unwrap()

            expect(result).toEqual(dlq('test dlq', new Error('test error')))
            expect(secondStep).not.toHaveBeenCalled()
        })

        it('should chain multiple synchronous steps', () => {
            const initialValue = { count: 0 }

            const step1: SyncPreprocessingStep<typeof initialValue, { count: number }> = (input) => {
                return success({ count: input.count + 1 })
            }

            const step2: SyncPreprocessingStep<{ count: number }, { count: number; doubled: number }> = (input) => {
                return success({ count: input.count, doubled: input.count * 2 })
            }

            const step3: SyncPreprocessingStep<{ count: number; doubled: number }, { final: string }> = (input) => {
                return success({ final: `count: ${input.count}, doubled: ${input.doubled}` })
            }

            const result = ProcessingPipeline.of(initialValue).pipe(step1).pipe(step2).pipe(step3).unwrap()

            expect(result).toEqual(success({ final: 'count: 1, doubled: 2' }))
        })

        it('should stop chain when step returns drop', () => {
            const initialValue = { count: 0 }

            const step1: SyncPreprocessingStep<typeof initialValue, { count: number }> = (input) => {
                return success({ count: input.count + 1 })
            }

            const step2: SyncPreprocessingStep<{ count: number }, { count: number }> = () => {
                return drop('step2 dropped')
            }

            const step3: SyncPreprocessingStep<{ count: number }, { final: string }> = (input) => {
                return success({ final: `count: ${input.count}` })
            }

            const result = ProcessingPipeline.of(initialValue).pipe(step1).pipe(step2).pipe(step3).unwrap()

            expect(result).toEqual(drop('step2 dropped'))
        })
    })

    describe('pipeAsync() - mixed sync/async steps', () => {
        it('should transition to AsyncProcessingPipeline', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const asyncPipeline = ProcessingPipeline.of(initialValue).pipeAsync(asyncStep)
            expect(asyncPipeline).toBeInstanceOf(AsyncProcessingPipeline)

            const result = await asyncPipeline.unwrap()
            expect(result).toEqual(success({ count: 2 }))
        })

        it('should not execute async step when result is failure', async () => {
            const initialValue = { count: 1 }
            const dropStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return drop('initial drop')
            }
            const asyncStep: AsyncPreprocessingStep<{ count: number }, { executed: boolean }> = jest.fn(async () => {
                await Promise.resolve()
                return success({ executed: true })
            })

            const result = await ProcessingPipeline.of(initialValue).pipe(dropStep).pipeAsync(asyncStep).unwrap()

            expect(result).toEqual(drop('initial drop'))
            expect(asyncStep).not.toHaveBeenCalled()
        })
    })
})

describe('AsyncProcessingPipeline', () => {
    describe('pipe() - synchronous steps on async pipeline', () => {
        it('should execute sync step after async step', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }
            const syncStep: SyncPreprocessingStep<{ count: number }, { count: number; final: boolean }> = (input) => {
                return success({ count: input.count, final: true })
            }

            const result = await ProcessingPipeline.of(initialValue).pipeAsync(asyncStep).pipe(syncStep).unwrap()

            expect(result).toEqual(success({ count: 2, final: true }))
        })

        it('should skip sync step when async result is failure', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async () => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return drop('async drop')
            }
            const syncStep: SyncPreprocessingStep<{ count: number }, { final: boolean }> = jest.fn((_input) => {
                return success({ final: true })
            })

            const result = await ProcessingPipeline.of(initialValue).pipeAsync(asyncStep).pipe(syncStep).unwrap()

            expect(result).toEqual(drop('async drop'))
            expect(syncStep).not.toHaveBeenCalled()
        })
    })

    describe('pipeAsync() - chaining async steps', () => {
        it('should chain multiple async steps', async () => {
            const initialValue = { count: 0 }

            const step1: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const step2: AsyncPreprocessingStep<{ count: number }, { count: number; doubled: number }> = async (
                input
            ) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count, doubled: input.count * 2 })
            }

            const result = await ProcessingPipeline.of(initialValue).pipeAsync(step1).pipeAsync(step2).unwrap()

            expect(result).toEqual(success({ count: 1, doubled: 2 }))
        })

        it('should stop chain when async step returns failure', async () => {
            const initialValue = { count: 0 }

            const step1: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const step2: AsyncPreprocessingStep<{ count: number }, { count: number }> = async () => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return redirect('async redirect', 'overflow-topic', false, true)
            }

            const step3: AsyncPreprocessingStep<{ count: number }, { final: string }> = jest.fn(async (input) => {
                await Promise.resolve()
                return success({ final: `count: ${input.count}` })
            })

            const result = await ProcessingPipeline.of(initialValue)
                .pipeAsync(step1)
                .pipeAsync(step2)
                .pipeAsync(step3)
                .unwrap()

            expect(result).toEqual(redirect('async redirect', 'overflow-topic', false, true))
            expect(step3).not.toHaveBeenCalled()
        })
    })

    describe('mixed sync and async steps', () => {
        it('should handle complex pipeline with mixed step types', async () => {
            const initialValue = { value: 'start' }

            const syncStep1: SyncPreprocessingStep<typeof initialValue, { value: string; step1: boolean }> = (
                input
            ) => {
                return success({ value: input.value + '-sync1', step1: true })
            }

            const asyncStep1: AsyncPreprocessingStep<
                { value: string; step1: boolean },
                { value: string; step1: boolean; async1: boolean }
            > = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ ...input, value: input.value + '-async1', async1: true })
            }

            const syncStep2: SyncPreprocessingStep<
                { value: string; step1: boolean; async1: boolean },
                { final: string }
            > = (input) => {
                return success({ final: `${input.value}-sync2` })
            }

            const result = await ProcessingPipeline.of(initialValue)
                .pipe(syncStep1)
                .pipeAsync(asyncStep1)
                .pipe(syncStep2)
                .unwrap()

            expect(result).toEqual(success({ final: 'start-sync1-async1-sync2' }))
        })
    })

    describe('error handling', () => {
        it('should handle async step that throws an error', async () => {
            const initialValue = { count: 1 }
            const errorStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async () => {
                await Promise.resolve()
                throw new Error('Step failed')
            }

            await expect(ProcessingPipeline.of(initialValue).pipeAsync(errorStep).unwrap()).rejects.toThrow(
                'Step failed'
            )
        })

        it('should handle sync step that throws an error', () => {
            const initialValue = { count: 1 }
            const errorStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                throw new Error('Sync step failed')
            }

            expect(() => {
                ProcessingPipeline.of(initialValue).pipe(errorStep).unwrap()
            }).toThrow('Sync step failed')
        })
    })
})

describe('Type safety and generics', () => {
    it('should maintain type safety through pipeline transformations', () => {
        interface Input1 {
            a: number
        }
        interface Input2 {
            b: string
        }
        interface Input3 {
            c: boolean
        }

        const step1: SyncPreprocessingStep<Input1, Input2> = (input) => {
            expect(typeof input.a).toBe('number')
            return success({ b: input.a.toString() })
        }

        const step2: SyncPreprocessingStep<Input2, Input3> = (input) => {
            expect(typeof input.b).toBe('string')
            return success({ c: input.b === '42' })
        }

        const result = ProcessingPipeline.of({ a: 42 }).pipe(step1).pipe(step2).unwrap()

        expect(result).toEqual(success({ c: true }))
    })

    it('should work with complex nested types', () => {
        interface ComplexInput {
            user: { id: string; name: string }
            metadata: { timestamp: number; source: string }
        }

        interface ProcessedOutput {
            userId: string
            displayName: string
            processedAt: string
        }

        const processStep: SyncPreprocessingStep<ComplexInput, ProcessedOutput> = (input) => {
            return success({
                userId: input.user.id,
                displayName: input.user.name.toUpperCase(),
                processedAt: new Date(input.metadata.timestamp).toISOString(),
            })
        }

        const complexInput: ComplexInput = {
            user: { id: 'user123', name: 'John Doe' },
            metadata: { timestamp: 1640995200000, source: 'api' },
        }

        const result = ProcessingPipeline.of(complexInput).pipe(processStep).unwrap()

        expect(result).toEqual(
            success({
                userId: 'user123',
                displayName: 'JOHN DOE',
                processedAt: '2022-01-01T00:00:00.000Z',
            })
        )
    })
})

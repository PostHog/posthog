import { Message } from 'node-rdkafka'

import { BranchingPipeline } from './branching-pipeline'
import { createContext } from './helpers'
import { Pipeline } from './pipeline.interface'
import { dlq, drop, isDlqResult, isOkResult, ok } from './results'
import { StartPipeline } from './start-pipeline'

describe('BranchingPipeline', () => {
    const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

    describe('basic branching', () => {
        it('should route to correct branch based on decision function', async () => {
            const decisionFn = (value: { type: string }) => value.type
            const branchA = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: `processed-${input.type}` }))
            )
            const branchB = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: `handled-${input.type}` }))
            )

            const branches = {
                a: branchA,
                b: branchB,
            }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>()
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const resultA = await pipeline.process(createContext(ok({ type: 'a' }), { message }))
            expect(isOkResult(resultA.result)).toBe(true)
            if (isOkResult(resultA.result)) {
                expect(resultA.result.value).toEqual({ result: 'processed-a' })
            }

            const resultB = await pipeline.process(createContext(ok({ type: 'b' }), { message }))
            expect(isOkResult(resultB.result)).toBe(true)
            if (isOkResult(resultB.result)) {
                expect(resultB.result.value).toEqual({ result: 'handled-b' })
            }
        })

        it('should execute previous pipeline before branching', async () => {
            const decisionFn = (value: { type: string }) => value.type.toLowerCase()
            const preprocessSpy = jest.fn()

            const branchA = new StartPipeline<{ type: string }, unknown>().pipe((input) => {
                preprocessSpy(input)
                return Promise.resolve(ok({ result: `processed-${input.type}` }))
            })

            const branches = { a: branchA }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ type: input.type.toUpperCase() }))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(ok({ type: 'a' }), { message }))

            // The previous pipeline uppercased the input, branch received the uppercased value
            expect(preprocessSpy).toHaveBeenCalledWith({ type: 'A' })
            expect(isOkResult(result.result)).toBe(true)
            if (isOkResult(result.result)) {
                expect(result.result.value).toEqual({ result: 'processed-A' })
            }
        })
    })

    describe('error handling', () => {
        it('should pass through non-OK results without executing decision function or branches', async () => {
            const decisionFn = jest.fn()
            const branch = new StartPipeline<{ type: string }, unknown>().pipe(() =>
                Promise.resolve(ok({ result: 'test' }))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>()
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(drop('dropped'), { message }))

            expect(decisionFn).not.toHaveBeenCalled()
            expect(result.result).toEqual(drop('dropped'))
        })

        it('should send to DLQ when branch name is not found', async () => {
            const decisionFn = (value: { type: string }) => value.type
            const branch = new StartPipeline<{ type: string }, unknown>().pipe(() =>
                Promise.resolve(ok({ result: 'test' }))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>()
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(ok({ type: 'unknown' }), { message }))

            expect(isDlqResult(result.result)).toBe(true)
            if (isDlqResult(result.result)) {
                expect(result.result.reason).toBe('Unknown branch: unknown')
                expect(result.result.error).toBeInstanceOf(Error)
            }
        })

        it('should preserve context when branch is not found', async () => {
            const decisionFn = (value: { type: string }) => value.type
            const branch = new StartPipeline<{ type: string }, unknown>().pipe(() =>
                Promise.resolve(ok({ result: 'test' }))
            )
            const branches = { a: branch }

            const existingSideEffect = Promise.resolve('existing')
            const existingWarning = { type: 'test_warning', details: {} }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>()
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(
                createContext(ok({ type: 'unknown' }), {
                    message,
                    sideEffects: [existingSideEffect],
                    warnings: [existingWarning],
                })
            )

            expect(result.context.sideEffects).toEqual([existingSideEffect])
            expect(result.context.warnings).toEqual([existingWarning])
        })

        it('should pass through previous pipeline errors', async () => {
            const decisionFn = jest.fn()
            const branch = new StartPipeline<{ type: string }, unknown>().pipe(() =>
                Promise.resolve(ok({ result: 'test' }))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe(() =>
                Promise.resolve(dlq('previous error', new Error('test')))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(ok({ type: 'a' }), { message }))

            expect(decisionFn).not.toHaveBeenCalled()
            expect(isDlqResult(result.result)).toBe(true)
            if (isDlqResult(result.result)) {
                expect(result.result.reason).toBe('previous error')
            }
        })
    })

    describe('side effects and warnings accumulation', () => {
        it('should accumulate side effects from previous context and branch result', async () => {
            const decisionFn = (value: { type: string }) => value.type

            const previousSideEffect = Promise.resolve('previous')
            const branchSideEffect = Promise.resolve('branch')

            const branch = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: input.type }, [branchSideEffect]))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok(input, [previousSideEffect]))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(ok({ type: 'a' }), { message }))

            // Previous side effect is passed through to branch, then branch adds its own
            expect(result.context.sideEffects).toEqual([previousSideEffect, branchSideEffect])
        })

        it('should accumulate warnings from previous context and branch result', async () => {
            const decisionFn = (value: { type: string }) => value.type

            const previousWarning = { type: 'previous_warning', details: {} }
            const branchWarning = { type: 'branch_warning', details: {} }

            const branch = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: input.type }, [], [branchWarning]))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok(input, [], [previousWarning]))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(createContext(ok({ type: 'a' }), { message }))

            // Previous warning is passed through to branch, then branch adds its own
            expect(result.context.warnings).toEqual([previousWarning, branchWarning])
        })

        it('should accumulate side effects and warnings from input context, previous pipeline, and branch', async () => {
            const decisionFn = (value: { type: string }) => value.type

            const inputSideEffect = Promise.resolve('input')
            const inputWarning = { type: 'input_warning', details: {} }

            const previousSideEffect = Promise.resolve('previous')
            const previousWarning = { type: 'previous_warning', details: {} }

            const branchSideEffect = Promise.resolve('branch')
            const branchWarning = { type: 'branch_warning', details: {} }

            const branch = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: input.type }, [branchSideEffect], [branchWarning]))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok(input, [previousSideEffect], [previousWarning]))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const result = await pipeline.process(
                createContext(ok({ type: 'a' }), {
                    message,
                    sideEffects: [inputSideEffect],
                    warnings: [inputWarning],
                })
            )

            // Side effects and warnings: input and previous are in previousResultWithContext,
            // then branch adds its own, then we merge previousResultWithContext + branchResult
            expect(result.context.sideEffects).toEqual([inputSideEffect, previousSideEffect, branchSideEffect])
            expect(result.context.warnings).toEqual([inputWarning, previousWarning, branchWarning])
        })
    })

    describe('decision function', () => {
        it('should call decision function with intermediate result value', async () => {
            const decisionFn = jest.fn().mockReturnValue('a')
            const branch = new StartPipeline<{ processed: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ result: input.processed }))
            )
            const branches = { a: branch }

            const previousPipeline = new StartPipeline<{ type: string }, unknown>().pipe((input) =>
                Promise.resolve(ok({ processed: input.type.toUpperCase() }))
            )
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            await pipeline.process(createContext(ok({ type: 'test' }), { message }))

            expect(decisionFn).toHaveBeenCalledWith({ processed: 'TEST' })
        })

        it('should support string union types as branch names', async () => {
            type BranchName = 'create' | 'update' | 'delete'
            type Context = { message: Message }
            const decisionFn = (value: { action: BranchName }): BranchName => value.action

            const createBranch = new StartPipeline<{ action: BranchName }, Context>().pipe((input) =>
                Promise.resolve(ok({ result: `created-${input.action}` }))
            )
            const updateBranch = new StartPipeline<{ action: BranchName }, Context>().pipe((input) =>
                Promise.resolve(ok({ result: `updated-${input.action}` }))
            )
            const deleteBranch = new StartPipeline<{ action: BranchName }, Context>().pipe((input) =>
                Promise.resolve(ok({ result: `deleted-${input.action}` }))
            )

            const branches: Record<BranchName, Pipeline<{ action: BranchName }, any, Context>> = {
                create: createBranch,
                update: updateBranch,
                delete: deleteBranch,
            }

            const previousPipeline = new StartPipeline<{ action: BranchName }, Context>()
            const pipeline = new BranchingPipeline(decisionFn, branches, previousPipeline)

            const createResult = await pipeline.process(
                createContext(ok({ action: 'create' as BranchName }), { message })
            )
            expect(isOkResult(createResult.result)).toBe(true)
            if (isOkResult(createResult.result)) {
                expect(createResult.result.value).toEqual({ result: 'created-create' })
            }

            const updateResult = await pipeline.process(
                createContext(ok({ action: 'update' as BranchName }), { message })
            )
            expect(isOkResult(updateResult.result)).toBe(true)
            if (isOkResult(updateResult.result)) {
                expect(updateResult.result.value).toEqual({ result: 'updated-update' })
            }

            const deleteResult = await pipeline.process(
                createContext(ok({ action: 'delete' as BranchName }), { message })
            )
            expect(isOkResult(deleteResult.result)).toBe(true)
            if (isOkResult(deleteResult.result)) {
                expect(deleteResult.result.value).toEqual({ result: 'deleted-delete' })
            }
        })
    })
})

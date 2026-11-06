import { Pipeline } from './pipeline.interface'
import { ok } from './results'
import { PromiseSchedulerInterface, SideEffectHandlingProcessor } from './side-effect-handling-pipeline'

describe('SideEffectHandlingProcessor', () => {
    let mockPromiseScheduler: jest.Mocked<PromiseSchedulerInterface>

    const createSubPipeline = (
        sideEffects: Promise<unknown>[]
    ): Pipeline<{ value: number }, { value: number }, Record<never, never>> => ({
        process: (input) =>
            Promise.resolve({
                result: ok(input.result.value),
                context: { ...input.context, sideEffects },
            }),
    })

    const processInput = { result: ok({ value: 1 }), context: { sideEffects: [], warnings: [] } }

    beforeEach(() => {
        mockPromiseScheduler = {
            schedule: jest.fn().mockImplementation((promise) => promise),
        }
    })

    it('should schedule side effects and clear them from the result', async () => {
        const sideEffect = Promise.resolve('side effect')
        const processor = new SideEffectHandlingProcessor(createSubPipeline([sideEffect]), mockPromiseScheduler, {
            await: false,
        })

        const result = await processor.process(processInput)

        expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffect)
        expect(result.context.sideEffects).toEqual([])
        expect(result.result).toEqual(ok({ value: 1 }))
    })

    it('should await side effects inline when configured', async () => {
        let sideEffectResolved = false
        const sideEffect = new Promise<void>((resolve) => {
            setTimeout(() => {
                sideEffectResolved = true
                resolve()
            }, 10)
        })
        const processor = new SideEffectHandlingProcessor(createSubPipeline([sideEffect]), mockPromiseScheduler, {
            await: true,
        })

        const result = await processor.process(processInput)

        expect(sideEffectResolved).toBe(true)
        expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        expect(result.context.sideEffects).toEqual([])
    })
})

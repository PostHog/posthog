import { newPipelineBuilder } from '../builders/helpers'
import { createContext } from '../helpers'
import { dlq, isOkResult, ok } from '../results'
import { TopHogRegistry, counter, createTopHogWrapper, timer } from './tophog'

describe('topHog wrapper', () => {
    function createMockTopHog(): TopHogRegistry & { record: jest.Mock; register: jest.Mock } {
        const record = jest.fn()
        const register = jest.fn().mockReturnValue({ record })
        return { record, register }
    }

    it('should record count metric on OK result', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(myStep, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.register).toHaveBeenCalledWith('events', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '42' }, 1)
    })

    it('should record time metric on OK result', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(myStep, [timer('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.register).toHaveBeenCalledWith('events', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '42' }, expect.any(Number))
    })

    it('should track multiple metrics with different keys', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number; userId: string }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number; userId: string }>()
            .pipe(
                topHog(myStep, [
                    counter('by_team', (input) => ({ team_id: String(input.teamId) })),
                    timer('by_user', (input) => ({ user_id: input.userId })),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42, userId: 'u_1' })))

        expect(mockTracker.register).toHaveBeenCalledWith('by_team', undefined)
        expect(mockTracker.register).toHaveBeenCalledWith('by_user', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '42' }, 1)
        expect(mockTracker.record).toHaveBeenCalledWith({ user_id: 'u_1' }, expect.any(Number))
    })

    it('should use custom metric name when provided', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(ok({ done: true }))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(step, [counter('heatmap_events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 7 })))

        expect(mockTracker.register).toHaveBeenCalledWith('heatmap_events', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '7' }, 1)
    })

    it('should track even on non-OK results from step', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(dlq('bad data'))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(step, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '1' }, 1)
    })

    it('should not track when descriptors are empty', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(ok({ done: true }))

        const pipeline = newPipelineBuilder<{ teamId: number }>().pipe(topHog(step, [])).build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(step).toHaveBeenCalled()
        expect(mockTracker.register).not.toHaveBeenCalled()
    })

    it('should preserve step name on wrapped function', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function namedStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(namedStep, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        const result = await pipeline.process(createContext(ok({ teamId: 5 })))

        expect(result.context.lastStep).toBe('namedStep')
    })

    it('should not interfere with step result or context propagation', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function trackedStep(input: { teamId: number }) {
            return Promise.resolve(ok({ processed: input.teamId }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(trackedStep, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        const result = await pipeline.process(createContext(ok({ teamId: 5 })))

        expect(isOkResult(result.result)).toBe(true)
        if (isOkResult(result.result)) {
            expect(result.result.value).toEqual({ processed: 5 })
        }
        expect(result.context.lastStep).toBe('trackedStep')
    })
})

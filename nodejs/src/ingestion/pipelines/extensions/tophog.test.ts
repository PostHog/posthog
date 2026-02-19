import { counter, timing } from '../../tophog/tophog'
import { newPipelineBuilder } from '../builders/helpers'
import { createContext } from '../helpers'
import { TopHogTracker } from '../pipeline.interface'
import { dlq, isOkResult, ok } from '../results'
import { createTopHogWrapper } from './tophog'

describe('topHog wrapper', () => {
    function createMockTopHog(): TopHogTracker & { increment: jest.Mock } {
        return { increment: jest.fn() }
    }

    it('should increment count metric on OK result', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(myStep, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.increment).toHaveBeenCalledWith('events.count', { team_id: '42' }, 1, undefined)
    })

    it('should increment time metric on OK result', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ processed: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(myStep, [timing('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.increment).toHaveBeenCalledWith(
            'events.time_ms',
            { team_id: '42' },
            expect.any(Number),
            undefined
        )
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
                    timing('by_user', (input) => ({ user_id: input.userId })),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42, userId: 'u_1' })))

        expect(mockTracker.increment).toHaveBeenCalledWith('by_team.count', { team_id: '42' }, 1, undefined)
        expect(mockTracker.increment).toHaveBeenCalledWith(
            'by_user.time_ms',
            { user_id: 'u_1' },
            expect.any(Number),
            undefined
        )
    })

    it('should use custom metric name when provided', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(ok({ done: true }))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(step, [counter('heatmap_events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 7 })))

        expect(mockTracker.increment).toHaveBeenCalledWith('heatmap_events.count', { team_id: '7' }, 1, undefined)
    })

    it('should track even on non-OK results from step', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(dlq('bad data'))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(topHog(step, [counter('events', (input) => ({ team_id: String(input.teamId) }))]))
            .build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(mockTracker.increment).toHaveBeenCalledWith('events.count', { team_id: '1' }, 1, undefined)
    })

    it('should not track when descriptors are empty', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(ok({ done: true }))

        const pipeline = newPipelineBuilder<{ teamId: number }>().pipe(topHog(step, [])).build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(step).toHaveBeenCalled()
        expect(mockTracker.increment).not.toHaveBeenCalled()
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

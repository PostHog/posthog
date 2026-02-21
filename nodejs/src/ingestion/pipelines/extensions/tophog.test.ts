import { newPipelineBuilder } from '../builders/helpers'
import { createContext } from '../helpers'
import { dlq, isOkResult, ok } from '../results'
import { TopHogRegistry, average, averageResult, counter, createTopHogWrapper, max, maxResult, timer } from './tophog'

describe('topHog wrapper', () => {
    function createMockTopHog(): TopHogRegistry & {
        record: jest.Mock
        register: jest.Mock
        registerMax: jest.Mock
        registerAverage: jest.Mock
    } {
        const record = jest.fn()
        const register = jest.fn().mockReturnValue({ record })
        const registerMax = jest.fn().mockReturnValue({ record })
        const registerAverage = jest.fn().mockReturnValue({ record })
        return { record, register, registerMax, registerAverage }
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

    it('should record average metric before step returns', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number; size: number }) {
            return Promise.resolve(ok({ done: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number; size: number }>()
            .pipe(
                topHog(myStep, [
                    average(
                        'avg_size',
                        (input) => ({ team_id: String(input.teamId) }),
                        (input) => input.size
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42, size: 1024 })))

        expect(mockTracker.registerAverage).toHaveBeenCalledWith('avg_size', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '42' }, 1024)
    })

    it('should record averageResult metric only on OK results', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ count: 5 }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(
                topHog(myStep, [
                    averageResult(
                        'avg_count',
                        (output) => ({ count: String(output.count) }),
                        (output) => output.count
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.registerAverage).toHaveBeenCalledWith('avg_count', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ count: '5' }, 5)
    })

    it('should not record averageResult on non-OK results', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(dlq('bad data'))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(
                topHog(step, [
                    averageResult(
                        'avg_count',
                        (_output: { count: number }) => ({ team_id: '1' }),
                        (output) => output.count
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(mockTracker.record).not.toHaveBeenCalled()
    })

    it('should record max metric before step returns', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number; size: number }) {
            return Promise.resolve(ok({ done: true }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number; size: number }>()
            .pipe(
                topHog(myStep, [
                    max(
                        'max_size',
                        (input) => ({ team_id: String(input.teamId) }),
                        (input) => input.size
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42, size: 2048 })))

        expect(mockTracker.registerMax).toHaveBeenCalledWith('max_size', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ team_id: '42' }, 2048)
    })

    it('should record maxResult metric only on OK results', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)

        function myStep(_input: { teamId: number }) {
            return Promise.resolve(ok({ size: 512 }))
        }

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(
                topHog(myStep, [
                    maxResult(
                        'max_output_size',
                        (output) => ({ size: String(output.size) }),
                        (output) => output.size
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 42 })))

        expect(mockTracker.registerMax).toHaveBeenCalledWith('max_output_size', undefined)
        expect(mockTracker.record).toHaveBeenCalledWith({ size: '512' }, 512)
    })

    it('should not record maxResult on non-OK results', async () => {
        const mockTracker = createMockTopHog()
        const topHog = createTopHogWrapper(mockTracker)
        const step = jest.fn().mockResolvedValue(dlq('bad data'))

        const pipeline = newPipelineBuilder<{ teamId: number }>()
            .pipe(
                topHog(step, [
                    maxResult(
                        'max_size',
                        (_output: { size: number }) => ({ team_id: '1' }),
                        (output) => output.size
                    ),
                ])
            )
            .build()

        await pipeline.process(createContext(ok({ teamId: 1 })))

        expect(mockTracker.record).not.toHaveBeenCalled()
    })
})

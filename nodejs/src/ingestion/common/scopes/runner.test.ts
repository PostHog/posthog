import { Component } from './component'
import { EmptyScope } from './empty-scope'
import { ScopeRunner } from './runner'
import { ScopeBuilder } from './scope-builder'
import { makeComponent } from './test-fixtures'

describe('ScopeRunner', () => {
    it('starts entries and assembles the container', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)

        const runner = new ScopeRunner(
            new EmptyScope(),
            () => ScopeBuilder.empty().add('a', a).add('b', b).components(),
            'phase'
        )
        const { value } = await runner.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(value).toEqual({ a: { name: 'a' }, b: { name: 'b' } })
    })

    it('tears down started entries in reverse order', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)
        const c = makeComponent('c', log)

        const runner = new ScopeRunner(
            new EmptyScope(),
            () => ScopeBuilder.empty().add('a', a).add('b', b).add('c', c).components(),
            'phase'
        )
        const { stop } = await runner.start()
        await stop()

        expect(log).toEqual(['start:a', 'start:b', 'start:c', 'stop:c', 'stop:b', 'stop:a'])
    })

    it('stops every entry even when stops throw, accumulating errors into an AggregateError', async () => {
        const log: string[] = []
        const failingStop = (name: string, message: string): Component<{ name: string }> => ({
            start: jest.fn(() => {
                log.push(`start:${name}`)
                return Promise.resolve({
                    value: { name },
                    stop: () => {
                        log.push(`stop:${name}`)
                        return Promise.reject(new Error(message))
                    },
                })
            }),
        })
        const a = makeComponent('a', log)
        const b = failingStop('b', 'b stop failed')
        const c = failingStop('c', 'c stop failed')

        const runner = new ScopeRunner(
            new EmptyScope(),
            () => ScopeBuilder.empty().add('a', a).add('b', b).add('c', c).components(),
            'phase'
        )
        const { stop } = await runner.start()

        // Both c and b throw, but neither aborts the loop, so a still stops —
        // no leaked resources — and both errors come back in the AggregateError.
        const error = await stop().then(
            () => null,
            (e: unknown) => e
        )
        if (!(error instanceof AggregateError)) {
            throw new Error(`expected an AggregateError, got ${String(error)}`)
        }
        expect(error.errors.map((e: Error) => e.message)).toEqual(['c stop failed', 'b stop failed'])
        expect(log).toEqual(['start:a', 'start:b', 'start:c', 'stop:c', 'stop:b', 'stop:a'])
    })

    it('rolls back already-started entries when a later one fails to start', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b: Component<{ name: string }> = {
            start: jest.fn(() => {
                log.push('start:b')
                return Promise.reject(new Error('b failed'))
            }),
        }

        const runner = new ScopeRunner(
            new EmptyScope(),
            () => ScopeBuilder.empty().add('a', a).add('b', b).components(),
            'phase'
        )

        await expect(runner.start()).rejects.toThrow('b failed')
        // Only entries that successfully started are rolled back, in reverse.
        expect(log).toEqual(['start:a', 'start:b', 'stop:a'])
    })

    it('surfaces the start error even when rollback teardown also fails', async () => {
        const log: string[] = []
        const a: Component<{ name: string }> = {
            start: jest.fn(() => {
                log.push('start:a')
                return Promise.resolve({
                    value: { name: 'a' },
                    stop: () => {
                        log.push('stop:a')
                        return Promise.reject(new Error('a stop failed'))
                    },
                })
            }),
        }
        const b: Component<{ name: string }> = {
            start: jest.fn(() => {
                log.push('start:b')
                return Promise.reject(new Error('b failed to start'))
            }),
        }

        const runner = new ScopeRunner(
            new EmptyScope(),
            () => ScopeBuilder.empty().add('a', a).add('b', b).components(),
            'phase'
        )

        // The rollback stop of `a` throws too. The start failure stays the
        // primary cause (first error), with the rollback error folded in.
        const error = await runner.start().then(
            () => null,
            (e: unknown) => e
        )
        if (!(error instanceof AggregateError)) {
            throw new Error(`expected an AggregateError, got ${String(error)}`)
        }
        expect(error.errors.map((e: Error) => e.message)).toEqual(['b failed to start', 'a stop failed'])
        expect(log).toEqual(['start:a', 'start:b', 'stop:a'])
    })
})

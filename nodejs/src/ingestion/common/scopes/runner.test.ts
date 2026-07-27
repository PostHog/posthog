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

    it('tears down all started entries', async () => {
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

        // Siblings are torn down in parallel, so stop ordering is not deterministic.
        expect(log.slice(0, 3)).toEqual(['start:a', 'start:b', 'start:c'])
        expect(log.slice(3).sort()).toEqual(['stop:a', 'stop:b', 'stop:c'])
        expect([a, b, c].map((component) => component.stopCalls)).toEqual([1, 1, 1])
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

        // Both c and b throw, but neither aborts teardown, so a still stops —
        // no leaked resources — and both errors come back in the AggregateError.
        const error = await stop().then(
            () => null,
            (e: unknown) => e
        )
        if (!(error instanceof AggregateError)) {
            throw new Error(`expected an AggregateError, got ${String(error)}`)
        }
        expect(error.errors.map((e: Error) => e.message).sort()).toEqual(['b stop failed', 'c stop failed'])
        expect(log.slice(0, 3)).toEqual(['start:a', 'start:b', 'start:c'])
        expect(log.slice(3).sort()).toEqual(['stop:a', 'stop:b', 'stop:c'])
    })

    it('lets a child override a parent key while still running both lifecycles', async () => {
        const log: string[] = []
        const parentA = makeComponent('parentA', log)
        const childA = makeComponent('childA', log)

        const parent = ScopeBuilder.empty().add('a', parentA).build('parent')
        const child = new ScopeRunner(parent, () => ({ a: childA }), 'child')

        const started = await child.start()
        // The child's value wins in the merged container, but both components
        // were started and both get torn down — the parent isn't orphaned.
        expect(started.value.a).toEqual({ name: 'childA' })
        expect(parentA.startCalls).toBe(1)
        expect(childA.startCalls).toBe(1)

        await started.stop()
        expect(parentA.stopCalls).toBe(1)
        expect(childA.stopCalls).toBe(1)
        expect(log).toEqual(['start:parentA', 'start:childA', 'stop:childA', 'stop:parentA'])
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

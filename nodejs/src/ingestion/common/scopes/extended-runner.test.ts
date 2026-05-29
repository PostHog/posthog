import { Component } from './component'
import { newScope } from './scope'
import { makeComponent } from './test-fixtures'

describe('ExtendedRunner', () => {
    it('extends a parent scope with a child scope', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (services, builder) => {
            // Services from the parent must be available here.
            expect(services.a).toEqual({ name: 'a' })
            return builder.add('b', b)
        })

        const started = await child.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(started.name).toBe('child')
        expect(started.container).toEqual({ a: { name: 'a' }, b: { name: 'b' } })

        await started.stop()
        // Child first, then parent.
        expect(log).toEqual(['start:a', 'start:b', 'stop:b', 'stop:a'])
    })

    it('refcounts the parent across multiple extensions', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)
        const c = makeComponent('c', log)

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const childB = parent.extend('childB', (_services, builder) => builder.add('b', b))
        const childC = parent.extend('childC', (_services, builder) => builder.add('c', c))

        const hB = await childB.start()
        const hC = await childC.start()

        // Parent boots exactly once even though both extensions started.
        expect(a.startCalls).toBe(1)
        expect(b.startCalls).toBe(1)
        expect(c.startCalls).toBe(1)

        await hB.stop()
        // Releasing one extension doesn't tear the parent down — the other
        // extension still holds it.
        expect(a.stopCalls).toBe(0)
        expect(b.stopCalls).toBe(1)

        await hC.stop()
        // Last extension released; parent now stops.
        expect(a.stopCalls).toBe(1)
        expect(c.stopCalls).toBe(1)
    })

    it('rolls back the parent when the child fails to start', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const failing: Component<{ name: string }> = {
            start: jest.fn(() => Promise.reject(new Error('child boom'))),
        }

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (_services, builder) => builder.add('bad', failing))

        await expect(child.start()).rejects.toThrow('child boom')

        // Parent was started, then released when the child failed.
        expect(a.startCalls).toBe(1)
        expect(a.stopCalls).toBe(1)
    })

    it('reconstructs the child on each restart', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        let buildCalls = 0

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (_services, builder) => {
            buildCalls++
            const b = makeComponent(`b${buildCalls}`, log)
            return builder.add('b', b)
        })

        const h1 = await child.start()
        await h1.stop()

        const h2 = await child.start()
        await h2.stop()

        expect(buildCalls).toBe(2)
        expect(a.startCalls).toBe(2)
        expect(a.stopCalls).toBe(2)
        expect(log).toEqual(['start:a', 'start:b1', 'stop:b1', 'stop:a', 'start:a', 'start:b2', 'stop:b2', 'stop:a'])
    })
})

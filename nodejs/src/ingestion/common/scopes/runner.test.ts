import { Component } from './component'
import { ComponentRunner } from './runner'
import { makeComponent } from './test-fixtures'

describe('ComponentRunner', () => {
    it('starts entries in registration order and assembles the container', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)

        const runner = new ComponentRunner('phase', { a, b })
        const { value } = await runner.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(value).toEqual({ a: { name: 'a' }, b: { name: 'b' } })
    })

    it('tears down started entries in reverse order', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)
        const c = makeComponent('c', log)

        const runner = new ComponentRunner('phase', { a, b, c })
        const { stop } = await runner.start()
        await stop()

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

        const runner = new ComponentRunner('phase', { a, b })

        await expect(runner.start()).rejects.toThrow('b failed')
        // Only entries that successfully started are rolled back, in reverse.
        expect(log).toEqual(['start:a', 'start:b', 'stop:a'])
    })
})

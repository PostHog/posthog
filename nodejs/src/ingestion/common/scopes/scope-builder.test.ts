import { ScopeBuilder } from './scope-builder'
import { makeComponent } from './test-fixtures'

describe('ScopeBuilder', () => {
    it('builds a scope whose container holds every added entry', async () => {
        const log: string[] = []
        const a = makeComponent('a', log)
        const b = makeComponent('b', log)

        const scope = ScopeBuilder.empty().add('a', a).add('b', b).build('phase')
        const started = await scope.start()

        expect(started.name).toBe('phase')
        expect(started.container).toEqual({ a: { name: 'a' }, b: { name: 'b' } })

        await started.stop()
    })

    it('does not start any component until the built scope is started', () => {
        const log: string[] = []
        const a = makeComponent('a', log)

        ScopeBuilder.empty().add('a', a).build('phase')

        expect(a.startCalls).toBe(0)
        expect(log).toEqual([])
    })
})

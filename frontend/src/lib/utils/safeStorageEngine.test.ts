import { createSafeStorageEngine } from 'lib/utils/safeStorageEngine'

describe('safeStorageEngine', () => {
    // Firefox raises a bare NS_ERROR_FAILURE from storage access, and
    // kea-localstorage touches the engine during render, so anything that
    // escapes here blanks the whole scene
    const throwingStorage = (): Storage => {
        const fail = (): never => {
            throw new Error('NS_ERROR_FAILURE')
        }
        return {
            get length(): number {
                return fail()
            },
            clear: fail,
            getItem: fail,
            key: fail,
            removeItem: fail,
            setItem: fail,
        }
    }

    it('swallows a throwing backing store instead of propagating', () => {
        const engine = createSafeStorageEngine(throwingStorage())

        expect(() => {
            engine['some.persisted.path'] = 'value'
        }).not.toThrow()
        expect(engine['some.persisted.path']).toBeUndefined()
        expect(() => delete engine['some.persisted.path']).not.toThrow()
        expect(() => engine.length).not.toThrow()
        expect(() => engine.getItem('some.persisted.path')).not.toThrow()
    })

    it('falls back to memory when localStorage is unavailable', () => {
        const engine = createSafeStorageEngine(undefined)

        engine['some.persisted.path'] = 'value'

        expect(engine['some.persisted.path']).toBe('value')
    })

    it('reads a missing key as undefined rather than null', () => {
        // kea-localstorage branches on `typeof engine[path] !== 'undefined'`, so
        // returning getItem's null would load null over every persisted
        // reducer's coded default
        const engine = createSafeStorageEngine(undefined)

        expect(engine['never.written']).toBeUndefined()
    })

    it('reports a startup storage failure once, on first key access', () => {
        // The memory fallback never throws, so a store blocked at startup would go
        // unreported without deferring the capture to first access. Isolate the module
        // to reset its once-per-session guard, and mock only this require's posthog-js.
        jest.resetModules()
        const capture = jest.fn()
        jest.doMock('posthog-js', () => ({ __esModule: true, default: { capture } }))
        const { createSafeStorageEngine: create } = require('lib/utils/safeStorageEngine')

        const engine = create(undefined, new Error('NS_ERROR_FAILURE'))
        // Deferred: nothing is reported until the engine is actually touched
        expect(capture).not.toHaveBeenCalled()

        expect(engine['first.access']).toBeUndefined()
        engine['second.access'] = 'value'

        expect(capture).toHaveBeenCalledTimes(1)
        expect(capture).toHaveBeenCalledWith('kea_localstorage_unavailable', { error: 'Error: NS_ERROR_FAILURE' })

        jest.dontMock('posthog-js')
    })
})

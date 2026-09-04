import { createSafeStorageEngine, resolveLocalStorage } from 'lib/utils/safeStorageEngine'

describe('safeStorageEngine', () => {
    // Firefox raises a bare NS_ERROR_FAILURE from storage access, and
    // kea-localstorage touches the engine during render, so anything that
    // escapes here blanks the whole scene
    const fail = (): never => {
        throw new Error('NS_ERROR_FAILURE')
    }

    const throwingStorage = (): Storage => ({
        get length(): number {
            return fail()
        },
        clear: fail,
        getItem: fail,
        key: fail,
        removeItem: fail,
        setItem: fail,
    })

    // A store at quota rejects writes while its reads keep working
    const readOnlyStorage = (seed: Record<string, string>): Storage => ({
        length: Object.keys(seed).length,
        clear: fail,
        getItem: (key: string): string | null => seed[key] ?? null,
        key: (index: number): string | null => Object.keys(seed)[index] ?? null,
        removeItem: fail,
        setItem: fail,
    })

    const realLocalStorage = Object.getOwnPropertyDescriptor(window, 'localStorage')

    afterEach(() => {
        if (realLocalStorage) {
            Object.defineProperty(window, 'localStorage', realLocalStorage)
        }
    })

    it('swallows a throwing backing store instead of propagating', () => {
        const engine = createSafeStorageEngine(throwingStorage())

        expect(() => {
            engine['some.persisted.path'] = 'value'
        }).not.toThrow()
        expect(() => delete engine['some.persisted.path']).not.toThrow()
        expect(() => engine.length).not.toThrow()
        expect(() => engine.getItem('some.persisted.path')).not.toThrow()
    })

    it('keeps a store that only rejects writes', () => {
        // A write probe would reject a store sitting at quota, and every one of
        // the 227 persisted reducers would then load its default over readable
        // saved state. Full storage is the case this guard exists for
        const atQuota = readOnlyStorage({ 'dismissed.prompt': '"yes"' })
        Object.defineProperty(window, 'localStorage', { value: atQuota, configurable: true })

        expect(resolveLocalStorage().storage).toBe(atQuota)
    })

    it('reads saved values from a store that only rejects writes', () => {
        const engine = createSafeStorageEngine(readOnlyStorage({ 'dismissed.prompt': '"yes"' }))

        engine['new.value'] = 'written'

        expect(engine['dismissed.prompt']).toBe('"yes"')
        // The rejected write still holds for this session
        expect(engine['new.value']).toBe('written')
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

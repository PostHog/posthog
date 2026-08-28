import { createGuardedStorageEngine } from 'lib/utils/guardedStorageEngine'

describe('createGuardedStorageEngine', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        window.localStorage.clear()
    })

    it('reads and writes through window.localStorage when it works', () => {
        const engine = createGuardedStorageEngine() as any

        engine['some.path'] = '{"a":1}'

        expect(window.localStorage.getItem('some.path')).toBe('{"a":1}')
        expect(engine['some.path']).toBe('{"a":1}')
    })

    it('returns undefined for a missing key so kea-localstorage treats it as absent', () => {
        const engine = createGuardedStorageEngine() as any

        expect(engine['missing.path']).toBeUndefined()
    })

    it('degrades to memory instead of throwing when localStorage access throws', () => {
        // Reproduces the Firefox blocked-storage state that blanked the app: bracket
        // access on window.localStorage throws a bare error during a logic build.
        jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('NS_ERROR_FAILURE')
        })
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('NS_ERROR_FAILURE')
        })

        const engine = createGuardedStorageEngine() as any

        expect(() => {
            engine['blocked.path'] = '{"b":2}'
        }).not.toThrow()
        expect(engine['blocked.path']).toBe('{"b":2}')
    })
})

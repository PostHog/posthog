import posthog from 'posthog-js'

import { createGuardedLocalStorageEngine } from './initKea'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { captureException: jest.fn() },
}))

describe('createGuardedLocalStorageEngine', () => {
    let originalLocalStorage: Storage

    beforeEach(() => {
        originalLocalStorage = window.localStorage
        ;(posthog.captureException as jest.Mock).mockClear()
    })

    afterEach(() => {
        Object.defineProperty(window, 'localStorage', { value: originalLocalStorage, configurable: true })
    })

    function installFakeLocalStorage(setterImpl: (key: string, value: string) => void): void {
        const store = new Map<string, string>()
        const fake: Storage = {
            get length() {
                return store.size
            },
            clear: () => store.clear(),
            getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
            key: (index: number) => Array.from(store.keys())[index] ?? null,
            removeItem: (key: string) => {
                store.delete(key)
            },
            setItem: setterImpl,
        }
        Object.defineProperty(window, 'localStorage', { value: fake, configurable: true })
    }

    it('forwards writes to the underlying storage when below quota', () => {
        const writes: Array<[string, string]> = []
        installFakeLocalStorage((key, value) => {
            writes.push([key, value])
        })

        const engine = createGuardedLocalStorageEngine()
        ;(engine as any)['some.key'] = '"hello"'

        expect(writes).toContainEqual(['some.key', '"hello"'])
    })

    it('swallows QuotaExceededError thrown on write and reports it once', () => {
        installFakeLocalStorage(() => {
            throw new DOMException('Quota exceeded', 'QuotaExceededError')
        })

        const engine = createGuardedLocalStorageEngine()
        expect(() => {
            ;(engine as any)['k1'] = '"v1"'
        }).not.toThrow()
        expect(() => {
            ;(engine as any)['k2'] = '"v2"'
        }).not.toThrow()

        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        expect((posthog.captureException as jest.Mock).mock.calls[0][1]).toEqual({ source: 'kea-localstorage' })
    })

    it('rethrows non-quota errors', () => {
        installFakeLocalStorage(() => {
            throw new TypeError('not a quota error')
        })

        const engine = createGuardedLocalStorageEngine()
        expect(() => {
            ;(engine as any)['k'] = '"v"'
        }).toThrow(TypeError)
        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('returns undefined when window.localStorage access throws', () => {
        Object.defineProperty(window, 'localStorage', {
            configurable: true,
            get(): Storage {
                throw new Error('SecurityError: localStorage disabled')
            },
        })

        expect(createGuardedLocalStorageEngine()).toBeUndefined()
    })
})

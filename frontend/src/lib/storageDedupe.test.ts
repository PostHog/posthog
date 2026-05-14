const ORIGINAL_SET = Storage.prototype.setItem
const ORIGINAL_REMOVE = Storage.prototype.removeItem
const ORIGINAL_GET = Storage.prototype.getItem

function freshEnvironment(): void {
    Storage.prototype.setItem = ORIGINAL_SET
    Storage.prototype.removeItem = ORIGINAL_REMOVE
    Storage.prototype.getItem = ORIGINAL_GET
    window.localStorage.clear()
    window.sessionStorage.clear()
    delete (window as unknown as { __phStorageDedupe?: unknown }).__phStorageDedupe
    jest.resetModules()
}

function loadDedupe(): typeof import('./storageDedupe') {
    return require('./storageDedupe')
}

describe('installStorageDedupe', () => {
    beforeEach(() => {
        freshEnvironment()
    })

    it.each([
        ['localStorage', 'localSetSkipped', 'localSetPassed'],
        ['sessionStorage', 'sessionSetSkipped', 'sessionSetPassed'],
    ] as const)(
        'on %s a duplicate setItem is skipped, changed setItem passes through',
        (storageName, skipKey, passKey) => {
            loadDedupe().installStorageDedupe()
            const storage = window[storageName]
            storage.setItem('k', 'v1')
            storage.setItem('k', 'v1')
            storage.setItem('k', 'v2')
            expect(storage.getItem('k')).toBe('v2')
            expect(window.__phStorageDedupe?.[skipKey]).toBe(1)
            expect(window.__phStorageDedupe?.[passKey]).toBe(2)
        }
    )

    it.each([
        ['localStorage', 'localRemoveSkipped', 'localRemovePassed'],
        ['sessionStorage', 'sessionRemoveSkipped', 'sessionRemovePassed'],
    ] as const)('on %s removeItem on an absent key is skipped', (storageName, skipKey, passKey) => {
        loadDedupe().installStorageDedupe()
        const storage = window[storageName]
        storage.setItem('present', 'x')
        storage.removeItem('present')
        storage.removeItem('never-existed')
        expect(window.__phStorageDedupe?.[passKey]).toBe(1)
        expect(window.__phStorageDedupe?.[skipKey]).toBe(1)
    })

    it('honors the sessionStorage kill switch and does not install', () => {
        window.sessionStorage.setItem('__ph_disable_storage_dedupe', '1')
        loadDedupe().installStorageDedupe()
        expect(window.__phStorageDedupe).toBeUndefined()
        window.localStorage.setItem('k', 'v')
        window.localStorage.setItem('k', 'v')
        expect(window.__phStorageDedupe).toBeUndefined()
        expect(window.localStorage.getItem('k')).toBe('v')
    })

    it('is idempotent — installing twice does not double-wrap', () => {
        const mod = loadDedupe()
        mod.installStorageDedupe()
        mod.installStorageDedupe()
        window.localStorage.setItem('k', 'v')
        window.localStorage.setItem('k', 'v')
        expect(window.__phStorageDedupe?.localSetSkipped).toBe(1)
        expect(window.__phStorageDedupe?.localSetPassed).toBe(1)
    })

    it('reflects out-of-band mutations because comparison reads native getItem each call', () => {
        loadDedupe().installStorageDedupe()
        window.localStorage.setItem('k', 'v1')
        // Mimic a write that bypasses the wrapper (e.g. an iframe with its
        // own Storage prototype, or devtools): call the captured native
        // setItem directly. The wrapper has no shadow cache, so the next
        // setItem with the original value must still pass through.
        ORIGINAL_SET.call(window.localStorage, 'k', 'external')
        window.localStorage.setItem('k', 'v1')
        expect(window.localStorage.getItem('k')).toBe('v1')
        expect(window.__phStorageDedupe?.localSetPassed).toBe(2)
        expect(window.__phStorageDedupe?.localSetSkipped).toBe(0)
    })
})

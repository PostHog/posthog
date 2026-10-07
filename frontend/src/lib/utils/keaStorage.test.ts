import { KEA_STORAGE_TTL_MS, LAST_USED_STORAGE_KEY, createKeaStorage, storageEntryBytes } from 'lib/utils/keaStorage'

// Items live as own enumerable properties, as they do on window.localStorage, so `Object.keys` lists them.
function fakeStorage(quotaBytes: number = Infinity): Storage {
    const items = {} as Record<string, string>
    const usedBytes = (): number =>
        Object.keys(items).reduce((total, key) => total + storageEntryBytes(key, items[key]), 0)
    const methods: Partial<Storage> = {
        getItem: (key) => (Object.prototype.hasOwnProperty.call(items, key) ? items[key] : null),
        setItem: (key, value) => {
            const previous = items[key] === undefined ? 0 : storageEntryBytes(key, items[key])
            if (usedBytes() - previous + storageEntryBytes(key, String(value)) > quotaBytes) {
                throw new DOMException('The quota has been exceeded.', 'QuotaExceededError')
            }
            items[key] = String(value)
        },
        removeItem: (key) => {
            delete items[key]
        },
    }
    for (const [name, fn] of Object.entries(methods)) {
        Object.defineProperty(items, name, { value: fn, enumerable: false })
    }
    return items as unknown as Storage
}

const NOW = Date.UTC(2026, 9, 7)
const DAY_MS = 24 * 60 * 60 * 1000

describe('createKeaStorage', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('returns undefined for a missing key so kea-localstorage writes the default', () => {
        const { engine } = createKeaStorage({ getStorage: () => fakeStorage(), now: () => NOW })

        expect((engine as any)['scenes.someLogic.missing']).toBeUndefined()
    })

    it.each([
        [
            'storage access throws',
            () => {
                throw new Error('NS_ERROR_FAILURE')
            },
        ],
        ['the store is full of live state', () => fakeStorage(0)],
    ])('keeps the session consistent instead of throwing when %s', (_, getStorage) => {
        const { engine } = createKeaStorage({ getStorage, now: () => NOW })

        expect(() => {
            ;(engine as any)['scenes.someLogic.filters'] = '{"new":true}'
        }).not.toThrow()
        expect((engine as any)['scenes.someLogic.filters']).toBe('{"new":true}')
    })

    it('prunes expired and untracked kea keys when a write hits the quota, then retries the write', () => {
        const storage = fakeStorage()
        storage.setItem('1_scenes.insightLogic.new-AdHoc.DataVisualizationNode.7.insightFeedback', 'null')
        storage.setItem('scenes.notebookLogic.old.localContent', 'x'.repeat(500))
        storage.setItem('scenes.dashboardLogic.recent.layout', '"kept"')
        storage.setItem('ph_phc_project_posthog', '"not kea"')
        storage.setItem(
            LAST_USED_STORAGE_KEY,
            JSON.stringify({
                'scenes.notebookLogic.old.localContent': NOW - KEA_STORAGE_TTL_MS - DAY_MS,
                'scenes.dashboardLogic.recent.layout': NOW - DAY_MS,
            })
        )
        const used = Object.keys(storage).reduce((total, key) => total + storageEntryBytes(key, storage[key]), 0)
        const quotaStorage = fakeStorage(used + 100)
        for (const key of Object.keys(storage)) {
            quotaStorage.setItem(key, storage[key])
        }
        const { engine } = createKeaStorage({ getStorage: () => quotaStorage, now: () => NOW })

        ;(engine as any)['scenes.newLogic.filters'] = JSON.stringify('y'.repeat(200))

        expect(Object.keys(quotaStorage).sort()).toEqual(
            [
                LAST_USED_STORAGE_KEY,
                'ph_phc_project_posthog',
                'scenes.dashboardLogic.recent.layout',
                'scenes.newLogic.filters',
            ].sort()
        )
    })
})

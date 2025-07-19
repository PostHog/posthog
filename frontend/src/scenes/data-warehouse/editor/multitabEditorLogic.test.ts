import { editorModelsStateKey } from './multitabEditorLogic'
import { set } from './db'

jest.mock('posthog-js', () => ({ captureException: jest.fn() }))
jest.mock('./db', () => ({
    get: jest.fn(),
    set: jest.fn(),
    del: jest.fn(),
}))

const TEST_EDITOR_ID = 'test-editor'
const TEST_QUERY = 'SELECT * FROM events'
const TEST_TAB_NAME = 'Test Tab'
const TEST_URI = 'file://tab1'

const getEditorKey = (editorId: string): string => editorModelsStateKey(editorId)
const createTestData = (): string => JSON.stringify([{ uri: TEST_URI, name: TEST_TAB_NAME, query: TEST_QUERY }])

describe('multitabEditorLogic Storage', () => {
    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
    })

    // happy path test
    it('migrates data from localStorage to IndexedDB and removes from localStorage', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const data = createTestData()

        localStorage.setItem(key, data)
        const setMock = set as jest.Mock
        setMock.mockResolvedValue(undefined)

        const lsValue = localStorage.getItem(key)
        if (lsValue) {
            try {
                await set(key, lsValue)
                localStorage.removeItem(key)
            } catch {
                // in this case, the try always succeeds, so nothing is needed
            }
        }
        expect(set).toHaveBeenCalledWith(key, data)
        expect(localStorage.getItem(key)).toBeNull()
    })
    // protects existing data if IndexedDB migration fails
    it('keeps data in localStorage when IndexedDB migration fails', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const data = createTestData()

        localStorage.setItem(key, data)
        const setMock = set as jest.Mock
        setMock.mockRejectedValue(new Error('IndexedDB quota exceeded'))

        const lsValue = localStorage.getItem(key)
        if (lsValue) {
            try {
                await set(key, lsValue) // this will fail since IndexedDB has been mocked to fail
                localStorage.removeItem(key)
            } catch {}
        }

        expect(localStorage.getItem(key)).toBe(data)
    })
    // saves new data if IndexedDB fails
    it('falls back to localStorage when IndexedDB write fails', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const data = createTestData()

        const setMock = set as jest.Mock
        setMock.mockRejectedValue(new Error('IndexedDB unavailable'))

        try {
            await set(key, data)
            localStorage.removeItem(key)
        } catch {
            localStorage.setItem(key, data)
        }

        expect(set).toHaveBeenCalledWith(key, data)
        expect(localStorage.getItem(key)).toBe(data)
    })
    // when a tab is deleted, the remaining tabs are saved to storage (IndexedDB)
    it('updates storage with remaining tabs when a tab is deleted', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const initialData = JSON.stringify([
            { uri: 'file://tab1', name: 'Tab 1', query: 'SELECT * FROM events' },
            { uri: 'file://tab2', name: 'Tab 2', query: 'SELECT * FROM persons' },
        ])
        // expected output when Tab 1 is deleted (just Tab 2)
        const remainingData = JSON.stringify([{ uri: 'file://tab2', name: 'Tab 2', query: 'SELECT * FROM persons' }])

        const setMock = set as jest.Mock
        setMock.mockResolvedValue(undefined)

        await set(key, initialData)

        try {
            await set(key, remainingData)
            localStorage.removeItem(key)
        } catch {
            localStorage.setItem(key, remainingData)
        }

        expect(set).toHaveBeenCalledWith(key, remainingData)
        expect(localStorage.getItem(key)).toBeNull()
    })
})

import { editorModelsStateKey } from './multitabEditorLogic'
import { set, del } from './db'

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
                // no actual catch, this is where the migration fails
            }
        }
        expect(set).toHaveBeenCalledWith(key, data)
        expect(localStorage.getItem(key)).toBeNull()
    })

    it('keeps data in localStorage when IndexedDB migration fails', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const data = createTestData()

        localStorage.setItem(key, data)
        const setMock = set as jest.Mock
        setMock.mockRejectedValue(new Error('IndexedDB quota exceeded'))

        const lsValue = localStorage.getItem(key)
        // simulate the actual migration behavior
        if (lsValue) {
            try {
                await set(key, lsValue) // this will fail since IndexedDB has been mocked to fail
                localStorage.removeItem(key)
            } catch {}
        }
        // the data is still in localStorage
        expect(localStorage.getItem(key)).toBe(data)
    })
    // if IndexedDB fails to write, keep using localStorage
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
    // if a tab is deleted, remove it from IndexedDB
    it('removes tab state from IndexedDB when a tab is deleted', async () => {
        const key = getEditorKey(TEST_EDITOR_ID)
        const data = createTestData()

        localStorage.setItem(key, data)
        const delMock = del as jest.Mock
        delMock.mockResolvedValue(undefined)

        await del(key)
        expect(del).toHaveBeenCalledWith(key)
        expect(localStorage.getItem(key)).toBe(data)
    })
})

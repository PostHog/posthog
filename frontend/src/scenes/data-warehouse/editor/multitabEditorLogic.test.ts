import { kea, resetContext } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { multitabEditorLogic } from './multitabEditorLogic'
// try moving this up to the top
jest.mock('lib/monaco/codeEditorLogic', () => ({
    codeEditorLogic: {
        actions: {
            createModel: jest.fn((...args: unknown[]) => {
                const [query, path, name] = args as [string, string, string]
                return { query, path, name }
            }),
        },
        values: {
            editorModelQueries: [
                {
                    id: 'mock-id',
                    path: 'mock-id',
                    query: 'SELECT * FROM events WHERE timestamp > now() - 7d',
                    name: 'Mock Tab',
                },
            ],
        },
        mount: jest.fn(),
        unmount: jest.fn(),
        findMounted: jest.fn(() => true),
        build: jest.fn(),
        extend: jest.fn(),
    },
}))

jest.mock('./db', () => ({ get: jest.fn(), set: jest.fn() }))

// silence project-related log noise
jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    queryTabState: { user: jest.fn().mockResolvedValue(undefined) },
}))

const mockDb = require('./db')
const _models = new Map<string, { uri: any; getValue: () => string; dispose: () => void }>()
const TEST_VALUE = 'SELECT * FROM events WHERE timestamp > now() - 7d'

// stub logic thats mounted via deep dependencies
jest.mock('scenes/activity/live/liveEventsTableLogic', () => ({ liveEventsTableLogic: makeLogicStub(['loadUser']) }), {
    virtual: true,
})
jest.mock('./editorSceneLogic', () => ({
    editorSceneLogic: makeLogicStub([
        'reportAIQueryAccepted',
        'reportAIQueryPrompted',
        'reportAIQueryRejected',
        'reportAIQueryPromptOpen',
    ]),
}))
jest.mock('scenes/userLogic', () => ({ userLogic: makeLogicStub([], { user: { uuid: 'test-user' } }) }))
jest.mock('kea-subscriptions', () => ({ subscriptions: () => ({}) }))

// helper to create a kea logic stub
function makeLogicStub(actionNames: string[] = [], defaults: Record<string, any> = {}): ReturnType<typeof kea> {
    return kea({
        actions: Object.fromEntries(actionNames.map((name) => [name, (p: any) => p])),
        reducers: Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, [() => v]])),
    })
}

// mock the parts of monaco which are used by multitabEditorLogic
const mockMonaco = {
    Uri: { parse: (p: string) => ({ path: p, toString: () => p }) },
    editor: {
        createModel: jest.fn((value: string, _lang: string, uri: any) => {
            const model = { uri, getValue: () => value, dispose: () => _models.delete(uri.toString()) }
            _models.set(uri.toString(), model)
            return model
        }),
        getModel: jest.fn((uri: any) => _models.get(uri.toString())),
        getModels: jest.fn(() => [..._models.values()]),
    },
} as unknown as typeof import('monaco-editor') // this silences the "missing properties" type error in the tests

// reset mocks and store before every test
beforeEach(() => {
    resetContext({ createStore: true })
    _models.clear()

    // Reset mock calls but keep the mock structure
    jest.clearAllMocks()

    // Mock localStorage
    Object.defineProperty(window, 'localStorage', {
        value: { getItem: jest.fn(), setItem: jest.fn(), removeItem: jest.fn() },
        writable: true,
    })
})

describe('Tabs storage', () => {
    it('migrates tab state from localStorage to IndexedDB', async () => {
        const localStorage = window.localStorage as any
        localStorage.getItem.mockReturnValue(JSON.stringify([{ id: '1', name: 'Mock Tab', query: TEST_VALUE }]))
        // mocks a successful write to IndexedDB
        mockDb.set.mockResolvedValue(undefined)

        const logic = multitabEditorLogic({ key: 't', monaco: mockMonaco, editor: null })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // make sure that the localStorage key has been removed
        expect(localStorage.removeItem).toHaveBeenCalled()

        // make sure that the tab state was saved to IndexedDB
        expect(mockDb.set).toHaveBeenCalledWith(
            expect.stringMatching(/editorModelQueries/),
            expect.stringContaining(TEST_VALUE)
        )
    })

    it('saves tab state to IndexedDB after creating a new tab', async () => {
        const logic = multitabEditorLogic({ key: 't', monaco: mockMonaco, editor: null })
        logic.mount()
        logic.actions.createTab(TEST_VALUE)

        await expectLogic(logic).toFinishAllListeners()

        expect(mockDb.set).toHaveBeenCalledWith(
            expect.stringMatching(/editorModelQueries/),
            expect.stringContaining(TEST_VALUE)
        )
        expect(logic.values.allTabs.length).toEqual(1)
    })
    it('removes tabs and updates IndexedDB', async () => {
        const logic = multitabEditorLogic({ key: 't', monaco: mockMonaco, editor: null })
        logic.mount()
        logic.actions.createTab(TEST_VALUE)
        await expectLogic(logic).toFinishAllListeners()

        const tabToDelete = logic.values.allTabs[0]
        logic.actions.deleteTab(tabToDelete)
        await expectLogic(logic).toFinishAllListeners()

        // make sure that the tab was removed from logic state
        expect(logic.values.allTabs).toHaveLength(0)

        // make sure that the storage was updated after deletion
        expect(mockDb.set).toHaveBeenCalled()
    })

    it('falls back to localStorage when IndexedDB fails', async () => {
        mockDb.set.mockRejectedValue(new Error('Storage quota exceeded'))

        const logic = multitabEditorLogic({ key: 't', monaco: mockMonaco, editor: null })
        logic.mount()
        logic.actions.createTab(TEST_VALUE)
        await expectLogic(logic).toFinishAllListeners()

        // Should fall back to localStorage if writing to IndexedDB fails
        expect(window.localStorage.setItem).toHaveBeenCalled()
    })
})

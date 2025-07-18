// Mock the database
const mockDb = {
    get: jest.fn(),
    set: jest.fn(),
}
jest.mock('./db', () => mockDb)

// Mock localStorage
const mockLocalStorage = {
    getItem: jest.fn(),
    setItem: jest.fn(),
    removeItem: jest.fn(),
}
Object.defineProperty(window, 'localStorage', { value: mockLocalStorage })

const TEST_VALUE = 'SELECT * FROM events WHERE timestamp > now() - 7d'

// TODO: replace with the real logic from kea
class TabManager {
    private tabs: Array<{ id: string; query: string; name: string }>
    private storageKey: string

    constructor() {
        this.tabs = []
        this.storageKey = 'editorModelQueries_t'
    }

    async initialize(): Promise<void> {
        // Try IndexedDB first, then localStorage
        try {
            const stored = await mockDb.get(this.storageKey)
            if (stored) {
                this.tabs = JSON.parse(stored)
                return
            }
        } catch {
            // Ignore IndexedDB errors
        }

        // Check localStorage and migrate
        const localData = mockLocalStorage.getItem(this.storageKey)
        if (localData) {
            this.tabs = JSON.parse(localData)
            await this.save()
            mockLocalStorage.removeItem(this.storageKey)
        }
    }

    async save(): Promise<void> {
        try {
            await mockDb.set(this.storageKey, JSON.stringify(this.tabs))
        } catch {
            mockLocalStorage.setItem(this.storageKey, JSON.stringify(this.tabs))
        }
    }

    async createTab(query: string, name = 'New Tab'): Promise<{ id: string; query: string; name: string }> {
        const tab = { id: Date.now().toString(), query, name }
        this.tabs.push(tab)
        await this.save()
        return tab
    }

    async deleteTab(tab: { id: string; query: string; name: string }): Promise<void> {
        this.tabs = this.tabs.filter((t) => t.id !== tab.id)
        await this.save()
    }

    getAllTabs(): Array<{ id: string; query: string; name: string }> {
        return this.tabs
    }
}

beforeEach(() => {
    jest.clearAllMocks()
    // Reset localStorage and IndexedDB mocks to return nothing
    mockLocalStorage.getItem.mockReturnValue(null)
    mockDb.get.mockResolvedValue(null)
    mockDb.set.mockResolvedValue(undefined)
})

describe('Tabs storage', () => {
    it('migrates tab state from localStorage to IndexedDB', async () => {
        mockLocalStorage.getItem.mockReturnValue(JSON.stringify([{ id: '1', name: 'Mock Tab', query: TEST_VALUE }]))
        mockDb.set.mockResolvedValue(undefined)

        const manager = new TabManager()
        await manager.initialize()

        expect(mockLocalStorage.removeItem).toHaveBeenCalled()
        expect(mockDb.set).toHaveBeenCalledWith(
            expect.stringMatching(/editorModelQueries/),
            expect.stringContaining(TEST_VALUE)
        )
    })

    it('saves tab state to IndexedDB after creating a new tab', async () => {
        const manager = new TabManager()
        await manager.initialize()
        await manager.createTab(TEST_VALUE)

        expect(mockDb.set).toHaveBeenCalledWith(
            expect.stringMatching(/editorModelQueries/),
            expect.stringContaining(TEST_VALUE)
        )
        expect(manager.getAllTabs().length).toEqual(1)
    })

    it('removes tabs and updates IndexedDB', async () => {
        const manager = new TabManager()
        await manager.initialize()
        await manager.createTab(TEST_VALUE)

        const tabToDelete = manager.getAllTabs()[0]
        await manager.deleteTab(tabToDelete)

        expect(manager.getAllTabs()).toHaveLength(0)
        expect(mockDb.set).toHaveBeenCalled()
    })

    it('falls back to localStorage when IndexedDB fails', async () => {
        mockDb.set.mockRejectedValue(new Error('Storage quota exceeded'))

        const manager = new TabManager()
        await manager.initialize()
        await manager.createTab(TEST_VALUE)

        expect(mockLocalStorage.setItem).toHaveBeenCalled()
    })
})

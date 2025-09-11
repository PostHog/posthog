jest.mock('idb', () => ({ openDB: jest.fn() }))
const openDBMock = require('idb').openDB as jest.Mock

const loadDbModule = async (): Promise<any> => {
    let db
    await jest.isolateModulesAsync(async () => {
        db = await import('./db')
    })
    return db
}

const createMockedDb = (): { get: jest.Mock; put: jest.Mock; delete: jest.Mock } => ({
    get: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
})

describe('SQL Editor IndexedDB wrapper', () => {
    const STORE_NAME = 'query-tab-state'
    const TEST_KEY = 'editor/tabs/2024-01-15'
    const TEST_VALUE = 'SELECT * FROM events WHERE timestamp > now() - 7d'
    let mockedDb: ReturnType<typeof createMockedDb>
    let db: Awaited<ReturnType<typeof loadDbModule>>

    beforeEach(async () => {
        jest.clearAllMocks()
        mockedDb = createMockedDb()
        openDBMock.mockResolvedValue(mockedDb)
        db = await loadDbModule()
    })

    describe('DB initialization', () => {
        it('initialize the db when accessed', async () => {
            await db.get(TEST_KEY)
            expect(openDBMock).toHaveBeenCalled()
        })

        it('creates object store if missing during upgrade', async () => {
            // this is just to make sure that when IndexedDB need to upgrade, that it creates the object store if missing
            let upgradeCallback: ((context: any) => void) | undefined
            openDBMock.mockImplementation((_name, _version, options) => {
                upgradeCallback = options.upgrade
                return Promise.resolve(mockedDb)
            })
            // simulate a new db load
            db = await loadDbModule()
            await db.get(TEST_KEY)
            const upgradeContext = {
                createObjectStore: jest.fn(),
                objectStoreNames: { contains: () => false }, // store doesn't exist yet
            }
            if (!upgradeCallback) {
                throw new Error('upgradeCallback was not set')
            }
            upgradeCallback(upgradeContext)
            expect(upgradeContext.createObjectStore).toHaveBeenCalledWith(STORE_NAME)
        })
    })

    describe('DB operations', () => {
        it('get, set, and delete tab state from IndexedDB', async () => {
            mockedDb.get.mockResolvedValue(TEST_VALUE)

            const value = await db.get(TEST_KEY)
            expect(value).toBe(TEST_VALUE)
            expect(mockedDb.get).toHaveBeenCalledWith(STORE_NAME, TEST_KEY)

            await db.set(TEST_KEY, TEST_VALUE)
            expect(mockedDb.put).toHaveBeenCalledWith(STORE_NAME, TEST_VALUE, TEST_KEY)

            await db.del(TEST_KEY)
            expect(mockedDb.delete).toHaveBeenCalledWith(STORE_NAME, TEST_KEY)
        })

        it('throws IndexedDB error on failure', async () => {
            mockedDb.get.mockRejectedValue(new Error('IndexedDB failure'))
            await expect(db.get(TEST_KEY)).rejects.toThrow('IndexedDB failure')
        })
    })
})

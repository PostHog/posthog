import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { listLibraries, updateLibrary } from '../../api'
import type { KnowledgeLibraryApi } from '../../generated/api.schemas'
import { learnedLibrariesLogic } from './learnedLibrariesLogic'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        detail: string | null
        constructor(message?: string, _status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.detail = data?.detail ?? null
        }
    }
    return { __esModule: true, default: {}, ApiError }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('../../api', () => ({
    listLibraries: jest.fn(),
    updateLibrary: jest.fn(),
}))

const LEARNED: KnowledgeLibraryApi = {
    id: 'library-learned',
    name: 'Learned',
    is_default: true,
    source_count: 3,
    repos: [],
}
const SUPPORT: KnowledgeLibraryApi = {
    id: 'library-support',
    name: 'Support',
    is_default: false,
    source_count: 1,
    repos: [],
}

describe('learnedLibrariesLogic', () => {
    let logic: ReturnType<typeof learnedLibrariesLogic.build>
    let saved: KnowledgeLibraryApi[]

    function receivingIds(libraries: KnowledgeLibraryApi[] | null): string[] {
        return (libraries ?? []).filter((library) => library.is_default).map((library) => library.id)
    }

    beforeEach(async () => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        // A small stand-in for the server: it keeps the libraries and applies each update to them.
        saved = [LEARNED, SUPPORT]
        ;(listLibraries as jest.Mock).mockImplementation(async () => saved)
        ;(updateLibrary as jest.Mock).mockImplementation(async (id: string, payload: { is_default?: boolean }) => {
            saved = saved.map((library) => (library.id === id ? { ...library, ...payload } : library))
            return saved.find((library) => library.id === id)
        })
        initKeaTests()
        logic = learnedLibrariesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('saves a second receiving library and unlocks the first one', async () => {
        expect(logic.values.libraryRows.map((row) => row.disabledReason)).toEqual([
            'At least one library must receive learned sources',
            undefined,
        ])

        logic.actions.setReceivesLearnedSources(SUPPORT.id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(receivingIds(saved)).toEqual([LEARNED.id, SUPPORT.id])
        expect(receivingIds(logic.values.libraries)).toEqual([LEARNED.id, SUPPORT.id])
        expect(logic.values.libraryRows.map((row) => row.disabledReason)).toEqual([undefined, undefined])
        expect(logic.values.savingLibraryIds).toEqual([])
    })

    it('shows the saved libraries again when the change is refused', async () => {
        ;(updateLibrary as jest.Mock).mockRejectedValue(new Error('refused'))

        logic.actions.setReceivesLearnedSources(SUPPORT.id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(receivingIds(logic.values.libraries)).toEqual([LEARNED.id])
        expect(logic.values.savingLibraryIds).toEqual([])
    })

    it('keeps a saved checkbox when a reload from another failure returned first', async () => {
        let finishSave: () => void = () => {}
        ;(updateLibrary as jest.Mock).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishSave = () => resolve({ ...SUPPORT, is_default: true })
                })
        )

        logic.actions.setReceivesLearnedSources(SUPPORT.id, true)
        // The reload answers before the save lands, so it still reports Support as not receiving.
        logic.actions.loadLibraries()
        await expectLogic(logic).toDispatchActions(['loadLibrariesSuccess'])
        expect(receivingIds(logic.values.libraries)).toEqual([LEARNED.id])
        finishSave()
        await expectLogic(logic).toFinishAllListeners()

        expect(receivingIds(logic.values.libraries)).toEqual([LEARNED.id, SUPPORT.id])
    })
})

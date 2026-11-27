import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

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

    function receivingIds(): string[] {
        return (logic.values.libraries ?? []).filter((library) => library.is_default).map((library) => library.id)
    }

    beforeEach(async () => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(listLibraries as jest.Mock).mockResolvedValue([LEARNED, SUPPORT])
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
        ;(updateLibrary as jest.Mock).mockResolvedValue({ ...SUPPORT, is_default: true })
        expect(logic.values.lastReceivingLibraryId).toBe(LEARNED.id)

        logic.actions.setReceivesLearnedSources(SUPPORT.id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(updateLibrary).toHaveBeenCalledWith(SUPPORT.id, { is_default: true })
        expect(receivingIds()).toEqual([LEARNED.id, SUPPORT.id])
        expect(logic.values.lastReceivingLibraryId).toBeNull()
        expect(logic.values.savingLibraryIds).toEqual([])
    })

    it('shows the saved libraries again when the change is refused', async () => {
        ;(updateLibrary as jest.Mock).mockRejectedValue(new Error('refused'))

        logic.actions.setReceivesLearnedSources(SUPPORT.id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(receivingIds()).toEqual([LEARNED.id])
        expect(lemonToast.error).toHaveBeenCalledWith('Could not change the library. Try again.')
        expect(logic.values.savingLibraryIds).toEqual([])
    })
})

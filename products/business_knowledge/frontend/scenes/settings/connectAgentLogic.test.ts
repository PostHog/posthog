import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    businessKnowledgeKeysCreate,
    businessKnowledgeKeysList,
    businessKnowledgeLibrariesList,
} from '../../generated/api'
import { ALL_KNOWLEDGE, connectAgentLogic } from './connectAgentLogic'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: {},
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('../../generated/api', () => ({
    businessKnowledgeLibrariesList: jest.fn(),
    businessKnowledgeKeysList: jest.fn(),
    businessKnowledgeKeysCreate: jest.fn(),
}))

const LIBRARY = { id: 'library-1', name: 'Public docs', is_default: false, source_count: 2, repos: [] }
const EXISTING_KEY = {
    id: 'key-1',
    label: 'Old agent',
    mask_value: 'phs_...aaaa',
    value: null,
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
    is_limited: false,
    library_id: null,
}
const NEW_KEY = {
    ...EXISTING_KEY,
    id: 'key-2',
    label: 'Docs agent',
    mask_value: 'phs_...bbbb',
    value: 'phs_new_key_value',
    is_limited: true,
    library_id: LIBRARY.id,
}

describe('connectAgentLogic', () => {
    let logic: ReturnType<typeof connectAgentLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(businessKnowledgeLibrariesList as jest.Mock).mockResolvedValue([LIBRARY])
        ;(businessKnowledgeKeysList as jest.Mock).mockResolvedValue([EXISTING_KEY])
        initKeaTests()
        logic = connectAgentLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setReads(LIBRARY.id)
        logic.actions.setLabel('  Docs agent  ')
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('keeps the new key value for the configuration and lists the key without it', async () => {
        ;(businessKnowledgeKeysCreate as jest.Mock).mockResolvedValue(NEW_KEY)

        logic.actions.createKey()
        await expectLogic(logic).toFinishAllListeners()

        expect(businessKnowledgeKeysCreate).toHaveBeenCalledWith('1', { label: 'Docs agent', library_id: LIBRARY.id })
        expect(logic.values.createdKey?.value).toBe('phs_new_key_value')
        expect(logic.values.listedKeys).toEqual([{ ...NEW_KEY, value: null }, EXISTING_KEY])
        expect(logic.values.createDisabledReason).toBe('Choose what the agent can read')
    })

    it('creates a key with no library when the admin chooses all business knowledge', async () => {
        ;(businessKnowledgeKeysCreate as jest.Mock).mockResolvedValue({
            ...NEW_KEY,
            is_limited: false,
            library_id: null,
        })
        logic.actions.setReads(ALL_KNOWLEDGE)

        logic.actions.createKey()
        await expectLogic(logic).toFinishAllListeners()

        expect(businessKnowledgeKeysCreate).toHaveBeenCalledWith('1', { label: 'Docs agent', library_id: null })
    })

    it('keeps the form and shows the reason when the key is refused', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        ;(businessKnowledgeKeysCreate as jest.Mock).mockRejectedValue(
            new ApiError('Bad Request', 400, undefined, { detail: 'A key with this name already exists.' })
        )

        logic.actions.createKey()
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith('A key with this name already exists.')
        expect(logic.values.createdKey).toBeNull()
        expect(logic.values.createDisabledReason).toBeUndefined()
        expect(logic.values.listedKeys).toEqual([EXISTING_KEY])
    })

    it('keeps a new key listed when an older list request answers after the create', async () => {
        let resolveList!: (keys: (typeof EXISTING_KEY)[]) => void
        ;(businessKnowledgeKeysList as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveList = resolve
            })
        )
        ;(businessKnowledgeKeysCreate as jest.Mock).mockResolvedValue(NEW_KEY)
        logic.actions.loadKeys()

        logic.actions.createKey()
        await expectLogic(logic).toDispatchActions(['createKeySuccess'])
        resolveList([EXISTING_KEY])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.listedKeys).toEqual([{ ...NEW_KEY, value: null }, EXISTING_KEY])
    })
})

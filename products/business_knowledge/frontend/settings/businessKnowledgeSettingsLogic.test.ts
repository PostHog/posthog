import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { businessKnowledgeSettingsPartialUpdate, businessKnowledgeSettingsRetrieve } from '../generated/api'
import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'

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

jest.mock('../generated/api', () => ({
    businessKnowledgeSettingsRetrieve: jest.fn(),
    businessKnowledgeSettingsPartialUpdate: jest.fn(),
}))

describe('businessKnowledgeSettingsLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeSettingsLogic.build>

    async function mountLogic(): Promise<void> {
        initKeaTests()
        logic = businessKnowledgeSettingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(businessKnowledgeSettingsRetrieve as jest.Mock).mockResolvedValue({
            learn_from_support_enabled: false,
            support_enabled: true,
        })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('loads settings without treating unresolved as off', async () => {
        let resolveGet!: (value: { learn_from_support_enabled: boolean; support_enabled: boolean }) => void
        ;(businessKnowledgeSettingsRetrieve as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveGet = resolve
            })
        )
        initKeaTests()
        logic = businessKnowledgeSettingsLogic()
        logic.mount()

        expect(logic.values.settings).toBeNull()

        resolveGet({ learn_from_support_enabled: true, support_enabled: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.settings?.learn_from_support_enabled).toBe(true)
    })

    it('locks the switch while a write is in flight and adopts the stored value', async () => {
        let resolvePatch!: (value: { learn_from_support_enabled: boolean; support_enabled: boolean }) => void
        ;(businessKnowledgeSettingsPartialUpdate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolvePatch = resolve
            })
        )
        await mountLogic()

        logic.actions.setLearnFromSupportEnabled(true)
        expect(logic.values.settingsSaving).toBe(true)

        resolvePatch({ learn_from_support_enabled: true, support_enabled: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.settingsSaving).toBe(false)
        expect(logic.values.settings?.learn_from_support_enabled).toBe(true)
    })

    it('snaps the switch back when the write is refused', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        ;(businessKnowledgeSettingsPartialUpdate as jest.Mock).mockRejectedValue(
            new ApiError('Bad Request', 400, undefined, { detail: 'Turn on Support to learn from resolved tickets.' })
        )
        await mountLogic()

        logic.actions.setLearnFromSupportEnabled(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.settings?.learn_from_support_enabled).toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith('Turn on Support to learn from resolved tickets.')
    })

    it('reverts the optimistic value even if the follow-up load fails', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        await mountLogic()
        ;(businessKnowledgeSettingsPartialUpdate as jest.Mock).mockRejectedValue(
            new ApiError('Bad Request', 400, undefined, { detail: 'Turn on Support to learn from resolved tickets.' })
        )
        ;(businessKnowledgeSettingsRetrieve as jest.Mock).mockRejectedValue(
            new ApiError('Server Error', 500, undefined, { detail: 'unavailable' })
        )

        logic.actions.setLearnFromSupportEnabled(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.settings?.learn_from_support_enabled).toBe(false)
    })
})

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    accountTrackRulesList,
    accountTrackRulesPreviewCreate,
    accountTrackRulesRunsList,
    accountTrackRulesUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountTrackRulesConfigApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountTrackRulesLogic } from './accountTrackRulesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountTrackRulesList: jest.fn(),
    accountTrackRulesPreviewCreate: jest.fn(),
    accountTrackRulesRunCreate: jest.fn(),
    accountTrackRulesRunsList: jest.fn(),
    accountTrackRulesUpdate: jest.fn(),
}))

const mockList = accountTrackRulesList as jest.MockedFunction<typeof accountTrackRulesList>
const mockPreview = accountTrackRulesPreviewCreate as jest.MockedFunction<typeof accountTrackRulesPreviewCreate>
const mockRuns = accountTrackRulesRunsList as jest.MockedFunction<typeof accountTrackRulesRunsList>
const mockUpdate = accountTrackRulesUpdate as jest.MockedFunction<typeof accountTrackRulesUpdate>

const CONFIG: AccountTrackRulesConfigApi = {
    schema_version: 1,
    version: 3,
    enabled: true,
    groups: [
        {
            conditions: [
                {
                    field: { kind: 'account_field', field: 'name' },
                    operator: 'icontains',
                    values: ['PostHog'],
                },
            ],
        },
    ],
}

describe('accountTrackRulesLogic', () => {
    let logic: ReturnType<typeof accountTrackRulesLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockList.mockResolvedValue(CONFIG)
        mockRuns.mockResolvedValue({ count: 0, results: [] })
        logic = accountTrackRulesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it('disables saving when the draft matches the saved configuration', () => {
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.canSave).toBe(false)
    })

    it('marks a preview stale as soon as the draft changes', async () => {
        mockPreview.mockResolvedValue({
            config_version: 3,
            eligible_active: 10,
            skipped_churned: 1,
            tracked: 8,
            ignored: 2,
            newly_ignored: 1,
            restored: 1,
            tracked_samples: [],
            ignored_samples: [],
            preview_token: 'signed-preview',
            validation_errors: [],
        })

        await expectLogic(logic, () => logic.actions.loadPreview()).toFinishAllListeners()
        expect(logic.values.previewIsCurrent).toBe(true)
        expect(logic.values.canRun).toBe(true)

        logic.actions.setEnabled(false)

        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.previewIsCurrent).toBe(false)
        expect(logic.values.canRun).toBe(false)
    })

    it('saves the versioned draft separately from applying it', async () => {
        const saved = { ...CONFIG, version: 4, enabled: false }
        mockUpdate.mockResolvedValue(saved)
        mockList.mockResolvedValue(saved)
        logic.actions.setEnabled(false)
        expect(logic.values.canSave).toBe(true)

        await expectLogic(logic, () => logic.actions.saveConfig()).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(String(logic.values.currentTeamId), {
            ...CONFIG,
            enabled: false,
        })
        expect(logic.values.draft).toEqual(saved)
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('does not allow saving an empty group', () => {
        logic.actions.addGroup()

        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.canSave).toBe(false)
    })
})

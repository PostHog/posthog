import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    accountTrackRulesList,
    accountTrackRulesPreviewCreate,
    accountTrackRulesRunCreate,
    accountTrackRulesRunsList,
    accountTrackRulesUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountTrackRulePreviewApi,
    AccountTrackRuleRunViewApi,
    AccountTrackRulesConfigApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

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
const mockRun = accountTrackRulesRunCreate as jest.MockedFunction<typeof accountTrackRulesRunCreate>
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

const PREVIEW: AccountTrackRulePreviewApi = {
    config_version: 3,
    eligible_active: 10,
    skipped_churned: 1,
    tracked: 8,
    ignored: 2,
    newly_ignored: 1,
    restored: 1,
    tracked_samples: [],
    ignored_samples: [],
    validation_errors: [],
}

const RUN: AccountTrackRuleRunViewApi = {
    id: '01980d7c-0000-7000-8000-000000000010',
    config_version: 4,
    trigger: 'manual',
    status: 'pending',
    eligible_active: 0,
    skipped_churned: 0,
    tracked: 0,
    ignored: 0,
    newly_ignored: 0,
    restored: 0,
    started_at: null,
    finished_at: null,
    error: null,
    created_by: 1,
    created_at: '2026-08-20T12:00:00Z',
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

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('runs saved enabled rules without requiring a preview', () => {
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.canSave).toBe(false)
        expect(logic.values.canRun).toBe(true)
    })

    it('polls scheduled runs until they finish', async () => {
        const scheduledRun: AccountTrackRuleRunViewApi = { ...RUN, trigger: 'scheduled', status: 'running' }
        const completedRun: AccountTrackRuleRunViewApi = {
            ...scheduledRun,
            status: 'completed',
            finished_at: '2026-08-20T12:01:00Z',
        }
        mockRuns
            .mockResolvedValueOnce({ count: 1, results: [scheduledRun] })
            .mockResolvedValueOnce({ count: 1, results: [completedRun] })

        jest.useFakeTimers()
        try {
            await expectLogic(logic, () => logic.actions.loadRuns()).toDispatchActions(['loadRunsSuccess'])
            expect(logic.values.runs).toEqual([scheduledRun])

            await jest.advanceTimersByTimeAsync(5_000)

            expect(logic.values.runs).toEqual([completedRun])
            expect(mockRuns).toHaveBeenCalledTimes(3)
        } finally {
            jest.useRealTimers()
        }
    })

    it('marks a preview stale only when its rule content changes', async () => {
        mockPreview.mockResolvedValue(PREVIEW)

        await expectLogic(logic, () => logic.actions.previewDraft()).toFinishAllListeners()
        expect(mockPreview).toHaveBeenCalledWith(String(logic.values.currentTeamId), CONFIG)
        expect(logic.values.previewMatchesDraft).toBe(true)

        logic.actions.setEnabled(false)

        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.previewMatchesDraft).toBe(false)
        expect(logic.values.canRun).toBe(false)
    })

    it('keeps the previous preview stale when a new preview fails', async () => {
        mockPreview.mockResolvedValueOnce(PREVIEW)
        await expectLogic(logic, () => logic.actions.previewDraft()).toFinishAllListeners()

        logic.actions.setEnabled(false)
        silenceKeaLoadersErrors()
        mockPreview.mockRejectedValueOnce(new ApiError('Invalid rule', 400))
        await expectLogic(logic, () => logic.actions.previewDraft()).toFinishAllListeners()

        expect(logic.values.previewedDraft).toEqual(CONFIG)
        expect(logic.values.previewResponse).toEqual(PREVIEW)
        expect(logic.values.previewMatchesDraft).toBe(false)
    })

    it('previews a valid unsaved configuration without saving it', async () => {
        mockPreview.mockResolvedValue(PREVIEW)
        logic.actions.setEnabled(false)

        await expectLogic(logic, () => logic.actions.previewDraft()).toFinishAllListeners()

        expect(mockPreview).toHaveBeenCalledWith(String(logic.values.currentTeamId), {
            ...CONFIG,
            enabled: false,
        })
        expect(logic.values.canPreview).toBe(true)
        expect(logic.values.previewMatchesDraft).toBe(true)
        expect(mockUpdate).not.toHaveBeenCalled()
    })

    it('saves and runs automatically when Track Rules are enabled', async () => {
        const disabled = { ...CONFIG, enabled: false }
        const enabled = { ...CONFIG, version: 4, enabled: true }
        mockUpdate.mockResolvedValue(enabled)
        mockRun.mockResolvedValue(RUN)
        logic.actions.loadConfigSuccess(disabled)

        await expectLogic(logic, () => logic.actions.toggleEnabled(true)).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(String(logic.values.currentTeamId), {
            ...disabled,
            enabled: true,
        })
        expect(mockRun).toHaveBeenCalledWith(String(logic.values.currentTeamId), {
            idempotency_key: expect.any(String),
            confirmed: true,
        })
        expect(mockUpdate.mock.invocationCallOrder[0]).toBeLessThan(mockRun.mock.invocationCallOrder[0])
        expect(logic.values.draft).toEqual(enabled)
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('saves rule changes without applying them', async () => {
        const saved = { ...CONFIG, version: 4, enabled: false }
        mockUpdate.mockResolvedValue(saved)
        logic.actions.setEnabled(false)

        await expectLogic(logic, () => logic.actions.saveConfig()).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(String(logic.values.currentTeamId), {
            ...CONFIG,
            enabled: false,
        })
        expect(mockRun).not.toHaveBeenCalled()
        expect(logic.values.draft).toEqual(saved)
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('does not allow saving or previewing an empty group', () => {
        logic.actions.addGroup()

        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.canSave).toBe(false)
        expect(logic.values.canPreview).toBe(false)
    })
})

import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import api from '~/lib/api'
import { ApiError } from '~/lib/api-error'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { EventsQuery, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { LLMPrompt, LLMPromptResolveResponse, PropertyFilterType, PropertyOperator } from '~/types'

import { llmPromptsNameLabelsDestroy, llmPromptsNameLabelsUpdate } from '../generated/api'
import { PromptAnalyticsScope, PromptMode, llmPromptLogic } from './llmPromptLogic'
import { validatePromptLabelName } from './utils'

jest.mock('../generated/api', () => ({
    llmPromptsNameLabelsUpdate: jest.fn(),
    llmPromptsNameLabelsDestroy: jest.fn(),
}))

const mockLabelsUpdate = llmPromptsNameLabelsUpdate as jest.MockedFunction<typeof llmPromptsNameLabelsUpdate>
const mockLabelsDestroy = llmPromptsNameLabelsDestroy as jest.MockedFunction<typeof llmPromptsNameLabelsDestroy>

const mockPrompt = {
    id: 'prompt-version-2',
    name: 'my-test-prompt',
    prompt: 'You are a helpful assistant.',
    version: 2,
    latest_version: 2,
    version_count: 2,
    first_version_created_at: '2024-01-01T00:00:00Z',
    is_latest: true,
    deleted: false,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    created_by: { id: 1, email: 'test@example.com' },
    versions: [
        {
            id: 'prompt-version-2',
            version: 2,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-02T00:00:00Z',
            is_latest: true,
        },
        {
            id: 'prompt-version-1',
            version: 1,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-01T00:00:00Z',
            is_latest: false,
        },
    ],
    has_more: false,
}

const productionLabelV1 = {
    id: 'label-1',
    name: 'production',
    prompt_name: 'my-test-prompt',
    version: 1,
    created_by: { id: 1, email: 'test@example.com' },
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
}

describe('llmPromptLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    function mountWithLabels(): ReturnType<typeof llmPromptLogic.build> {
        const { versions, has_more, ...promptFields } = mockPrompt
        jest.spyOn(api.llmPrompts, 'resolveByName').mockResolvedValue({
            prompt: promptFields,
            versions,
            has_more,
            labels: [productionLabelV1],
        } as unknown as LLMPromptResolveResponse)
        return llmPromptLogic({ promptName: 'my-test-prompt' })
    }

    it('defaults to view mode for existing prompts', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            mode: PromptMode.View,
            analyticsScope: PromptAnalyticsScope.Selected,
        })

        logic.unmount()
    })

    it('builds related traces query for the selected version by default', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const query = logic.values.relatedTracesQuery
        expect(query).not.toBeNull()
        expect(query?.kind).toBe(NodeKind.DataTableNode)

        const source = query?.source as TracesQuery
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_version',
                value: 2,
                operator: PropertyOperator.Exact,
            },
        ])
        expect(source.dateRange?.date_from).toBe('-1d')

        logic.unmount()
    })

    it('switches traces and usage filters to all versions scope', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)
        logic.actions.setAnalyticsScope(PromptAnalyticsScope.AllVersions)

        await expectLogic(logic).toMatchValues({
            analyticsScope: PromptAnalyticsScope.AllVersions,
            promptUsagePropertyFilter: [
                {
                    key: 'prompt_name',
                    type: PropertyFilterType.Event,
                    value: 'my-test-prompt',
                    operator: PropertyOperator.Exact,
                },
            ],
        })

        const query = logic.values.relatedTracesQuery
        const source = query?.source as TracesQuery
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
        ])
        expect(source.dateRange?.date_from).toBe('-1d')

        logic.unmount()
    })

    it('applies traces query overrides and preserves scope-specific property filters', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const initialQuery = logic.values.relatedTracesQuery
        expect(initialQuery).not.toBeNull()

        logic.actions.setRelatedTracesQuery({
            ...initialQuery!,
            source: {
                ...(initialQuery!.source as TracesQuery),
                dateRange: {
                    date_from: '-7d',
                    date_to: undefined,
                },
            },
        })

        let source = logic.values.relatedTracesQuery?.source as TracesQuery
        expect(source.dateRange?.date_from).toBe('-7d')
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_version',
                value: 2,
                operator: PropertyOperator.Exact,
            },
        ])

        logic.actions.setAnalyticsScope(PromptAnalyticsScope.AllVersions)
        source = logic.values.relatedTracesQuery?.source as TracesQuery
        expect(source.dateRange?.date_from).toBe('-7d')
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
        ])

        logic.unmount()
    })

    it('builds a view-all-traces URL using the selected version filter', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const url = logic.values.viewAllTracesUrl
        expect(url).toContain('/ai-observability/traces?')

        const parsedUrl = new URL(url, 'https://posthog.test')
        const decodedFilter = JSON.parse(parsedUrl.searchParams.get('filters') || '[]')
        expect(decodedFilter).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_version',
                value: 2,
                operator: PropertyOperator.Exact,
            },
        ])
        expect(parsedUrl.searchParams.get('date_from')).toBe('-1d')

        logic.unmount()
    })

    it('uses the currently selected related-traces date range in view-all-traces URL', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const initialQuery = logic.values.relatedTracesQuery
        expect(initialQuery).not.toBeNull()

        logic.actions.setRelatedTracesQuery({
            ...initialQuery!,
            source: {
                ...(initialQuery!.source as TracesQuery),
                dateRange: {
                    date_from: '-30d',
                    date_to: '-1d',
                },
            },
        })

        const url = logic.values.viewAllTracesUrl
        const parsedUrl = new URL(url, 'https://posthog.test')

        expect(parsedUrl.searchParams.get('date_from')).toBe('-30d')
        expect(parsedUrl.searchParams.get('date_to')).toBe('-1d')

        logic.unmount()
    })

    it('defaults usage trend and log date ranges to last 1 day', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        expect(logic.values.promptUsageTrendQuery.source.dateRange?.date_from).toBe('-1d')
        expect((logic.values.promptUsageLogQuery.source as EventsQuery).after).toBe('-1d')

        logic.actions.setAnalyticsScope(PromptAnalyticsScope.AllVersions)

        expect(logic.values.promptUsageTrendQuery.source.dateRange?.date_from).toBe('-1d')
        expect((logic.values.promptUsageLogQuery.source as EventsQuery).after).toBe('-1d')

        logic.unmount()
    })

    it('includes the selected version in breadcrumbs', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        expect(logic.values.breadcrumbs[1].name).toBe('my-test-prompt v2')

        logic.unmount()
    })

    it('preserves form edits and advances the base version on a publish conflict', async () => {
        const { versions, has_more, ...promptFields } = mockPrompt
        const conflictingLatest = {
            ...promptFields,
            id: 'prompt-version-3',
            prompt: 'Someone else edited this prompt.',
            version: 3,
            latest_version: 3,
            version_count: 3,
        }

        jest.spyOn(api.llmPrompts, 'resolveByName')
            .mockResolvedValueOnce({ prompt: promptFields, versions, has_more } as unknown as LLMPromptResolveResponse)
            .mockResolvedValue({ prompt: conflictingLatest, versions, has_more } as unknown as LLMPromptResolveResponse)
        jest.spyOn(api.llmPrompts, 'update').mockRejectedValue(
            new ApiError('conflict', 409, undefined, { detail: 'The prompt changed since you opened it.' })
        )

        const logic = llmPromptLogic({ promptName: 'my-test-prompt' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])

        logic.actions.setMode(PromptMode.Edit)
        logic.actions.setPromptFormValues({ name: 'my-test-prompt', prompt: 'My in-progress edit.' })

        logic.actions.submitPromptForm()
        await expectLogic(logic).toDispatchActions(['submitPromptFormFailure'])

        expect(logic.values.promptForm.prompt).toBe('My in-progress edit.')
        expect(logic.values.publishConflict).toEqual({ latestVersion: 3 })
        expect(logic.values.prompt).toMatchObject({ latest_version: 3 })
        expect(logic.values.mode).toBe(PromptMode.Edit)

        logic.unmount()
    })

    it('guards cancel behind a confirmation only when the form is dirty', async () => {
        const { versions, has_more, ...promptFields } = mockPrompt
        jest.spyOn(api.llmPrompts, 'resolveByName').mockResolvedValue({
            prompt: promptFields,
            versions,
            has_more,
        } as unknown as LLMPromptResolveResponse)
        const dialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})

        const logic = llmPromptLogic({ promptName: 'my-test-prompt' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])

        // Clean form: cancel exits edit mode directly, no dialog
        logic.actions.setMode(PromptMode.Edit)
        logic.actions.cancelEditing()
        expect(logic.values.mode).toBe(PromptMode.View)
        expect(dialogSpy).not.toHaveBeenCalled()

        // Dirty form: cancel keeps edit mode until the dialog's discard is confirmed
        logic.actions.setMode(PromptMode.Edit)
        logic.actions.setPromptFormValues({ prompt: 'My in-progress edit.' })
        logic.actions.cancelEditing()
        expect(logic.values.mode).toBe(PromptMode.Edit)
        expect(dialogSpy).toHaveBeenCalledTimes(1)

        dialogSpy.mock.calls[0][0].primaryButton?.onClick?.(undefined as any)
        expect(logic.values.mode).toBe(PromptMode.View)
        expect(logic.values.promptForm.prompt).toBe(mockPrompt.prompt)

        logic.unmount()
    })

    it('reflects edit mode in the url', async () => {
        const { versions, has_more, ...promptFields } = mockPrompt
        jest.spyOn(api.llmPrompts, 'resolveByName').mockResolvedValue({
            prompt: promptFields,
            versions,
            has_more,
        } as unknown as LLMPromptResolveResponse)

        const logic = llmPromptLogic({ promptName: 'my-test-prompt' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])

        logic.actions.setMode(PromptMode.Edit)
        expect(router.values.searchParams.edit).toBe(true)

        logic.actions.setMode(PromptMode.View)
        expect(router.values.searchParams.edit).toBeUndefined()

        logic.unmount()
    })

    it('routes publish through the review step for existing prompts', async () => {
        const { versions, has_more, ...promptFields } = mockPrompt
        jest.spyOn(api.llmPrompts, 'resolveByName').mockResolvedValue({
            prompt: promptFields,
            versions,
            has_more,
        } as unknown as LLMPromptResolveResponse)
        const updateSpy = jest.spyOn(api.llmPrompts, 'update').mockResolvedValue({
            ...promptFields,
            id: 'prompt-version-3',
            version: 3,
            latest_version: 3,
        } as unknown as LLMPrompt)

        const logic = llmPromptLogic({ promptName: 'my-test-prompt' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])
        logic.actions.setMode(PromptMode.Edit)

        // Empty content skips the review and goes to submit, surfacing validation errors
        logic.actions.setPromptFormValues({ prompt: '   ' })
        logic.actions.requestPublish()
        expect(logic.values.isPublishReviewOpen).toBe(false)
        expect(updateSpy).not.toHaveBeenCalled()

        // Real edits open the review without hitting the API
        logic.actions.setPromptFormValues({ prompt: 'My edited prompt.' })
        logic.actions.requestPublish()
        expect(logic.values.isPublishReviewOpen).toBe(true)
        expect(updateSpy).not.toHaveBeenCalled()

        // Confirming from the review publishes with the typed description and closes it
        logic.actions.setVersionDescription('Tightened the refusal criteria')
        logic.actions.submitPromptForm()
        await expectLogic(logic).toDispatchActions(['submitPromptFormSuccess'])
        expect(updateSpy).toHaveBeenCalledTimes(1)
        expect(updateSpy).toHaveBeenCalledWith('my-test-prompt', {
            prompt: 'My edited prompt.',
            base_version: 2,
            version_description: 'Tightened the refusal criteria',
        })
        expect(logic.values.isPublishReviewOpen).toBe(false)

        logic.unmount()
    })

    it('moving a label requires confirmation and replaces its previous position', async () => {
        const dialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const logic = mountWithLabels()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])
        expect(logic.values.labelsByVersion).toEqual({ 1: [expect.objectContaining({ name: 'production' })] })

        logic.actions.requestSetLabel('production', 2)

        expect(dialogSpy).toHaveBeenCalledTimes(1)
        expect(mockLabelsUpdate).not.toHaveBeenCalled()

        mockLabelsUpdate.mockResolvedValue({ ...productionLabelV1, version: 2 } as any)
        await dialogSpy.mock.calls[0][0].primaryButton?.onClick?.(undefined as any)

        expect(mockLabelsUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'my-test-prompt', 'production', {
            version: 2,
        })
        expect(logic.values.labelsByVersion).toEqual({
            2: [expect.objectContaining({ name: 'production', version: 2 })],
        })

        logic.unmount()
    })

    it('keeps labels unchanged and resyncs after losing a concurrent label write', async () => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => {})
        const logic = mountWithLabels()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])

        mockLabelsUpdate.mockRejectedValue(
            new ApiError('conflict', 409, undefined, {
                detail: 'This label was changed by someone else at the same time. Try again.',
            })
        )
        logic.actions.requestSetLabel('staging', 2)
        await expectLogic(logic).toDispatchActions(['setLabel', 'loadPrompt', 'loadPromptSuccess'])

        expect(toastSpy).toHaveBeenCalledWith('This label was changed by someone else at the same time. Try again.')
        expect(logic.values.labelsByVersion).toEqual({ 1: [expect.objectContaining({ name: 'production' })] })

        logic.unmount()
    })

    it('keeps a label visible when its delete request fails', async () => {
        const dialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        jest.spyOn(lemonToast, 'error').mockImplementation(() => {})
        const logic = mountWithLabels()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])

        mockLabelsDestroy.mockRejectedValue(new ApiError('server error', 500))
        logic.actions.requestRemoveLabel('production')
        expect(dialogSpy).toHaveBeenCalledTimes(1)

        await dialogSpy.mock.calls[0][0].primaryButton?.onClick?.(undefined as any)

        expect(logic.values.labelsByVersion).toEqual({ 1: [expect.objectContaining({ name: 'production' })] })

        logic.unmount()
    })

    it.each([
        ['production', true],
        ['release-2.1_final', true],
        ['latest', false],
        ['123', false],
        ['Production', false],
        ['-leading-dash', false],
    ])('validatePromptLabelName(%s) accepts=%s', (name, accepted) => {
        expect(validatePromptLabelName(name) === undefined).toBe(accepted)
    })

    it('resets new prompt form values after unmount and remount', async () => {
        const firstMount = llmPromptLogic({ promptName: 'new' })
        firstMount.mount()

        firstMount.actions.setPromptFormValues({
            name: 'stale-name',
            prompt: 'stale prompt',
        })
        expect(firstMount.values.promptForm.name).toBe('stale-name')
        expect(firstMount.values.promptForm.prompt).toBe('stale prompt')
        firstMount.unmount()

        const secondMount = llmPromptLogic({ promptName: 'new' })
        secondMount.mount()

        expect(secondMount.values.promptForm.name).toBe('')
        expect(secondMount.values.promptForm.prompt).toBe('')
        secondMount.unmount()
    })
})

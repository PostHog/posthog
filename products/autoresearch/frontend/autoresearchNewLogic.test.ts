import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { autoresearchNewLogic } from './autoresearchNewLogic'
import {
    autoresearchCreate,
    autoresearchResolveTemplateCreate,
    autoresearchTemplatesList,
    autoresearchTrainCreate,
    autoresearchValidateCreate,
} from './generated/api'

jest.mock('./generated/api', () => ({
    autoresearchCreate: jest.fn(),
    autoresearchTrainCreate: jest.fn(),
    autoresearchValidateCreate: jest.fn(),
    autoresearchTemplatesList: jest.fn(),
    autoresearchResolveTemplateCreate: jest.fn(),
}))

const mockCreate = autoresearchCreate as jest.Mock
const mockValidate = autoresearchValidateCreate as jest.Mock
const mockTemplates = autoresearchTemplatesList as jest.Mock
const mockResolve = autoresearchResolveTemplateCreate as jest.Mock
const mockCreate = autoresearchCreate as jest.Mock
const mockTrain = autoresearchTrainCreate as jest.Mock

function validation(
    warnings: { code: string; severity: string }[],
    overrides: Record<string, unknown> = {}
): Record<string, unknown> {
    return {
        can_proceed: !warnings.some((w) => w.severity === 'error'),
        requires_acknowledgement: false,
        estimated_training_rows: 1000,
        positive_count: 100,
        negative_count: 900,
        base_rate: 0.1,
        inference_population_size: 2000,
        warnings: warnings.map((w) => ({ ...w, message: w.code })),
        error: null,
        ...overrides,
    }
}

const TEMPLATES = [
    {
        key: 'likely_active_soon',
        display_name: 'Likely active soon',
        description: '',
        default_horizon_days: 7,
        requires_user_event: false,
        requires_activity_resolution: true,
        notes: '',
    },
    {
        key: 'feature_adoption',
        display_name: 'Likely to adopt a feature',
        description: '',
        default_horizon_days: 14,
        requires_user_event: true,
        requires_activity_resolution: false,
        notes: '',
    },
]

function resolved(overrides: Record<string, unknown>): Record<string, unknown> {
    return {
        template_key: 'likely_active_soon',
        display_name: 'Likely active soon',
        description: '',
        suggested_name: 'Likely active soon',
        target_event: '$pageview',
        resolved_activity_event: '$pageview',
        activity_event_alternatives: [],
        horizon_days: 7,
        training_lookback_days: 180,
        training_population: { kind: 'performed_event_within_days', days: 30, event: '$pageview' },
        inference_population: { kind: 'performed_event_within_days', days: 30, event: '$pageview' },
        output_person_property: 'predicted_p_active_soon_pageview_7d',
        notes: '',
        ...overrides,
    }
}

async function settle(logic: ReturnType<typeof autoresearchNewLogic.build>): Promise<void> {
    await jest.advanceTimersByTimeAsync(1000)
    await expectLogic(logic).toFinishAllListeners()
}

describe('autoresearchNewLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.useFakeTimers()
        initKeaTests()
        mockValidate.mockResolvedValue({ can_proceed: true, warnings: [] })
        mockTemplates.mockResolvedValue(TEMPLATES)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a valid form', {}, 1],
        ['a cleared horizon', { horizon_days: NaN }, 0],
        ['a cleared training lookback', { training_lookback_days: NaN }, 0],
        ['a horizon out of range', { horizon_days: 0 }, 0],
        ['a fractional horizon', { horizon_days: 1.5 }, 0],
        ['a fractional training lookback', { training_lookback_days: 30.5 }, 0],
    ])('sends %s to the validate endpoint only when the day fields are valid', async (_, days, expectedCalls) => {
        const logic = autoresearchNewLogic()
        logic.mount()

        logic.actions.setNewPipelineValues({ target_event: '$pageview', ...days })
        await settle(logic)

        expect(mockValidate).toHaveBeenCalledTimes(expectedCalls)
        expect(logic.values.validationFailed).toBe(false)
    })

    it('scores all identified users when only the separate training population has filters', async () => {
        const trainingFilter: PersonPropertyFilter = {
            key: 'plan',
            value: 'pro',
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Person,
        }
        const logic = autoresearchNewLogic()
        logic.mount()

        logic.actions.setNewPipelineValues({
            target_event: '$pageview',
            separate_training_population: true,
            training_population: [trainingFilter],
        })
        await settle(logic)

        expect(mockValidate).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.objectContaining({
                training_population: { properties: [trainingFilter] },
                inference_population: { properties: [] },
            })
        )
    })

    it('fills the form from an activity template, validates with its population, and lets an unedited name follow a template switch', async () => {
        mockResolve.mockResolvedValue(resolved({}))
        const logic = autoresearchNewLogic()
        logic.mount()
        await settle(logic)

        logic.actions.selectTemplate('likely_active_soon')
        await settle(logic)

        expect(mockResolve).toHaveBeenCalledTimes(1)
        expect(mockResolve.mock.calls[0][1]).toEqual({ template_key: 'likely_active_soon' })
        expect(logic.values.newPipeline).toMatchObject({
            name: 'Likely active soon',
            target_event: '$pageview',
            horizon_days: 7,
            output_person_property: 'predicted_p_active_soon_pageview_7d',
        })
        const population = { kind: 'performed_event_within_days', days: 30, event: '$pageview' }
        expect(mockValidate).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.objectContaining({ training_population: population, inference_population: population })
        )

        mockResolve.mockResolvedValueOnce(
            resolved({ template_key: 'feature_adoption', suggested_name: 'Likely to adopt a feature: $pageview' })
        )
        logic.actions.selectTemplate('feature_adoption')
        await settle(logic)
        expect(logic.values.newPipeline).toMatchObject({
            template_key: 'feature_adoption',
            name: 'Likely to adopt a feature: $pageview',
        })
    })

    it('asks for a target before it resolves a template that needs one, and keeps an edited name and lookback', async () => {
        mockResolve.mockImplementation((_team, { target_event, horizon_days }) =>
            Promise.resolve(
                resolved({
                    template_key: 'feature_adoption',
                    suggested_name: `Likely to adopt a feature: ${target_event}`,
                    target_event,
                    resolved_activity_event: null,
                    horizon_days: horizon_days ?? 14,
                    training_population: { kind: 'active_not_performed_target', active_within_days: 30 },
                    inference_population: { kind: 'active_not_performed_target', active_within_days: 30 },
                })
            )
        )
        const logic = autoresearchNewLogic()
        logic.mount()
        await settle(logic)

        logic.actions.selectTemplate('feature_adoption')
        await settle(logic)
        expect(mockResolve).not.toHaveBeenCalled()
        expect(logic.values.newPipeline).toMatchObject({ template_key: 'feature_adoption', horizon_days: 14 })

        logic.actions.setNewPipelineValues({ training_lookback_days: 365 })
        logic.actions.setNewPipelineValues({ target_event: 'file_shared' })
        await settle(logic)
        expect(mockResolve.mock.calls[0][1]).toEqual({
            template_key: 'feature_adoption',
            target_event: 'file_shared',
            horizon_days: 14,
        })
        expect(logic.values.newPipeline).toMatchObject({
            name: 'Likely to adopt a feature: file_shared',
            training_lookback_days: 365,
            inference_population_kind: { kind: 'active_not_performed_target', active_within_days: 30 },
        })

        logic.actions.setNewPipelineValues({ name: 'Sharing adoption' })
        logic.actions.setNewPipelineValues({ horizon_days: 30 })
        await settle(logic)
        expect(mockResolve).toHaveBeenCalledTimes(2)
        expect(logic.values.newPipeline).toMatchObject({ name: 'Sharing adoption', horizon_days: 30 })
    })

    it.each([
        ['experiment budget', { iteration_budget: NaN }],
        ['training lookback', { training_lookback_days: 5 }],
    ])('opens Advanced when an invalid %s blocks submit', async (_, advancedValues) => {
        const logic = autoresearchNewLogic()
        logic.mount()
        logic.actions.setNewPipelineValues({ name: 'Model', target_event: '$pageview', ...advancedValues })
        await settle(logic)
        expect(logic.values.advancedOpen).toBe(false)

        logic.actions.submitNewPipeline()
        await settle(logic)
        expect(logic.values.advancedOpen).toBe(true)
        expect(mockCreate).not.toHaveBeenCalled()
    })

    it('blocks creation until the template resolves for the current target', async () => {
        mockResolve.mockResolvedValue(resolved({}))
        mockCreate.mockResolvedValue({ id: 'pipeline-1', name: 'Likely active soon' })
        const logic = autoresearchNewLogic()
        logic.mount()
        await settle(logic)
        logic.actions.selectTemplate('likely_active_soon')
        await settle(logic)

        mockResolve.mockRejectedValueOnce({ detail: 'Resolve failed' })
        logic.actions.setNewPipelineValues({ target_event: '$autocapture' })
        await settle(logic)
        logic.actions.submitNewPipeline()
        await settle(logic)
        expect(mockCreate).not.toHaveBeenCalled()

        logic.actions.selectTemplate('likely_active_soon')
        await settle(logic)
        logic.actions.submitNewPipeline()
        await settle(logic)
        expect(mockCreate).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['no warnings', [], {}, 'ready', ['pass', 'pass', 'pass', 'pass'], false],
        [
            'a non-blocking warning',
            [{ code: 'extreme_imbalance', severity: 'warning' }],
            {},
            'warnings',
            ['pass', 'warning', 'pass', 'pass'],
            false,
        ],
        [
            'a blocking data warning',
            [{ code: 'low_negatives', severity: 'error' }],
            {},
            'blocked',
            ['pass', 'pass', 'fail', 'pass'],
            true,
        ],
        [
            'a horizon longer than the lookback, which skips the data queries',
            [{ code: 'horizon_exceeds_lookback', severity: 'error' }],
            {
                estimated_training_rows: 0,
                positive_count: 0,
                negative_count: 0,
                base_rate: 0,
                inference_population_size: null,
            },
            'blocked',
            ['skipped', 'skipped', 'skipped', 'fail'],
            true,
        ],
    ])(
        'builds the readiness checklist from a response with %s',
        async (_, warnings, overrides, readiness, statuses, startTrainingDisabled) => {
            mockValidate.mockResolvedValue(validation(warnings, overrides))
            const logic = autoresearchNewLogic()
            logic.mount()

            logic.actions.setNewPipelineValues({ target_event: '$pageview' })
            await settle(logic)

            expect(logic.values.readiness).toBe(readiness)
            expect(logic.values.readinessChecks.map((check) => check.status)).toEqual(statuses)
            expect(!!logic.values.startTrainingDisabledReason).toBe(startTrainingDisabled)
            expect(logic.values.saveDraftDisabledReason).toBeUndefined()
        }
    )

    it.each([
        ['train', 'blocked', 0, 0],
        ['draft', 'blocked', 1, 0],
        ['train', 'ready', 1, 1],
        ['draft', 'ready', 1, 0],
    ] as const)(
        'with the %s action on a %s definition, creates %d model and starts %d run',
        async (intent, readiness, expectedCreates, expectedTrains) => {
            mockValidate.mockResolvedValue(
                validation(readiness === 'blocked' ? [{ code: 'low_volume', severity: 'error' }] : [])
            )
            mockCreate.mockResolvedValue({ id: 'pipeline-1', name: 'Sharing' })
            mockTrain.mockResolvedValue({ id: 'run-1', status: 'running' })
            const logic = autoresearchNewLogic()
            logic.mount()

            logic.actions.setNewPipelineValues({ name: 'Sharing', target_event: 'file_shared' })
            await settle(logic)
            logic.actions.submitWithIntent(intent)
            await settle(logic)

            expect(mockCreate).toHaveBeenCalledTimes(expectedCreates)
            expect(mockTrain.mock.calls.map((call) => call[1])).toEqual(expectedTrains ? ['pipeline-1'] : [])
            expect(router.values.location.pathname.endsWith(urls.autoresearchPipeline('pipeline-1'))).toBe(
                expectedCreates === 1
            )
        }
    )

    it.each([
        ['a validation error', { detail: 'A training run is already running' }, 'A training run is already running'],
        [
            'a usage limit',
            new ApiError("You've reached your usage limit.", 429, undefined, {
                code: 'usage_limit_exceeded',
                error: "You've reached your usage limit.",
            }),
            "You've reached your usage limit.",
        ],
    ])('opens the created model and shows the reason when training fails with %s', async (_, error, reason) => {
        const toastError = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        mockCreate.mockResolvedValue({ id: 'pipeline-1', name: 'Sharing' })
        mockTrain.mockRejectedValue(error)
        const logic = autoresearchNewLogic()
        logic.mount()

        logic.actions.setNewPipelineValues({ name: 'Sharing', target_event: 'file_shared' })
        await settle(logic)
        logic.actions.submitWithIntent('train')
        await settle(logic)

        expect(mockTrain).toHaveBeenCalledTimes(1)
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining(reason))
        expect(router.values.location.pathname).toContain(urls.autoresearchPipeline('pipeline-1'))
    })
})

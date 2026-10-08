import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { autoresearchNewLogic } from './autoresearchNewLogic'
import {
    autoresearchCreate,
    autoresearchResolveTemplateCreate,
    autoresearchTemplatesList,
    autoresearchValidateCreate,
} from './generated/api'

jest.mock('./generated/api', () => ({
    autoresearchCreate: jest.fn(),
    autoresearchValidateCreate: jest.fn(),
    autoresearchTemplatesList: jest.fn(),
    autoresearchResolveTemplateCreate: jest.fn(),
}))

const mockCreate = autoresearchCreate as jest.Mock
const mockValidate = autoresearchValidateCreate as jest.Mock
const mockTemplates = autoresearchTemplatesList as jest.Mock
const mockResolve = autoresearchResolveTemplateCreate as jest.Mock

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
})

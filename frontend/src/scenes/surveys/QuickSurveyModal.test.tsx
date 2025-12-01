import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, FeatureFlagEvaluationRuntime, type FeatureFlagType } from '~/types'

import { QuickSurveyForm } from './QuickSurveyModal'

jest.mock('scenes/surveys/SurveyAppearancePreview', () => ({
    SurveyAppearancePreview: () => <div>Preview</div>,
}))
jest.mock('scenes/surveys/SurveySettings', () => ({
    SurveyPopupToggle: () => <div>Survey Toggle</div>,
}))
jest.mock('scenes/surveys/AddEventButton', () => ({
    AddEventButton: ({ onEventSelect }: any) => <button onClick={() => onEventSelect('test-event')}>Add event</button>,
}))

const mockFlag: FeatureFlagType = {
    id: 1,
    key: 'test-flag',
    name: 'Test Flag',
    filters: { groups: [], multivariate: null, payloads: {} },
    deleted: false,
    active: true,
    created_at: '2023-01-01',
    created_by: null,
    is_simple_flag: false,
    rollout_percentage: null,
    ensure_experience_continuity: false,
    experiment_set: [],
    rollback_conditions: [],
    performed_rollback: false,
    can_edit: true,
    tags: [],
    features: [],
    usage_dashboard: undefined,
    analytics_dashboards: [],
    has_enriched_analytics: false,
    surveys: [],
    updated_at: '2023-01-01',
    version: 1,
    last_modified_by: null,
    evaluation_tags: [],
    is_remote_configuration: false,
    has_encrypted_payloads: false,
    status: 'ACTIVE',
    evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
    user_access_level: AccessControlLevel.Admin,
}

describe('QuickSurveyForm', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions': { results: [], count: 0 },
                '/api/projects/:team_id/surveys': { results: [], count: 0 },
                '/api/projects/:team_id/surveys/responses_count': {},
            },
            post: {
                '/api/projects/:team_id/surveys': () => [200, { id: 'new-survey' }],
            },
            patch: {
                '/api/environments/@current/add_product_intent/': () => [200, {}],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('disables create button when question is empty', async () => {
        render(<QuickSurveyForm flag={mockFlag} />)

        const questionInput = screen.getByPlaceholderText('What do you think?')
        userEvent.clear(questionInput)

        expect(screen.getByRole('button', { name: /create & launch/i })).toHaveAttribute('aria-disabled', 'true')
    })

    it('creates survey with selected events in conditions', async () => {
        let capturedRequest: any
        useMocks({
            post: {
                '/api/projects/:team_id/surveys': async (req) => {
                    capturedRequest = await req.json()
                    return [200, { id: 'new-survey' }]
                },
            },
        })

        render(<QuickSurveyForm flag={mockFlag} />)

        // Add an event
        await userEvent.click(screen.getByRole('button', { name: /add event/i }))
        expect(screen.getByText('test-event')).toBeInTheDocument()

        // Create survey
        await userEvent.click(screen.getByRole('button', { name: /create & launch/i }))

        await waitFor(() => {
            expect(capturedRequest).not.toBeUndefined()
            expect(capturedRequest.conditions.events.values).toEqual([{ name: 'test-event' }])
            expect(capturedRequest.linked_flag_id).toBe(1)
        })
    })

    it('creates survey without events when none selected', async () => {
        let capturedRequest: any
        useMocks({
            post: {
                '/api/projects/:team_id/surveys': async (req) => {
                    capturedRequest = await req.json()
                    return [200, { id: 'new-survey' }]
                },
            },
        })

        render(<QuickSurveyForm flag={mockFlag} />)

        await userEvent.click(screen.getByRole('button', { name: /create & launch/i }))

        await waitFor(() => {
            expect(capturedRequest).not.toBeUndefined()
            expect(capturedRequest.conditions.events.values).toEqual([])
        })
    })

    it('includes selected variant in survey conditions', async () => {
        const multivariateFlag: FeatureFlagType = {
            ...mockFlag,
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
                payloads: {},
            },
        }

        let capturedRequest: any
        useMocks({
            post: {
                '/api/projects/:team_id/surveys': async (req) => {
                    capturedRequest = await req.json()
                    return [200, { id: 'new-survey' }]
                },
            },
        })

        render(<QuickSurveyForm flag={multivariateFlag} />)

        // Select the 'test' variant
        const testVariantRadio = screen.getByLabelText(/test/i, { selector: 'input[type="radio"]' })
        await userEvent.click(testVariantRadio)

        await userEvent.click(screen.getByRole('button', { name: /create & launch/i }))

        await waitFor(() => {
            expect(capturedRequest).not.toBeUndefined()
            expect(capturedRequest.conditions.linkedFlagVariant).toBe('test')
        })
    })
})

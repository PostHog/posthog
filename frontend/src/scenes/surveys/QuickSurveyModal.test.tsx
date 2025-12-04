import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { QuickSurveyForm } from './QuickSurveyModal'
import { QuickSurveyType } from './quick-create/types'
import { FunnelContext } from './utils/opportunityDetection'

jest.mock('scenes/surveys/SurveyAppearancePreview', () => ({
    SurveyAppearancePreview: () => <div data-testid="preview">Preview</div>,
}))
jest.mock('scenes/surveys/SurveySettings', () => ({
    SurveyPopupToggle: () => null,
}))

const mockFlag = {
    id: 1,
    name: 'Test Flag',
    filters: { groups: [], multivariate: null, payloads: {} },
} as unknown as FeatureFlagType

const mockFunnel: FunnelContext = {
    insightName: 'Test Funnel',
    conversionRate: 0.3,
    steps: [
        { kind: 'EventsNode', name: 'step_one', properties: [{ key: 'url', value: ['/checkout'], operator: 'exact' }] },
        { kind: 'EventsNode', name: 'step_two' },
    ] as FunnelContext['steps'],
}

describe('QuickSurveyForm API payloads', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions': { results: [], count: 0 },
                '/api/projects/:team_id/surveys': { results: [] },
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

    it('sends correct payload for feature flag survey', async () => {
        let capturedRequest: any
        useMocks({
            post: {
                '/api/projects/:team_id/surveys': async (req) => {
                    capturedRequest = await req.json()
                    return [200, { id: 'new-survey' }]
                },
            },
        })

        render(<QuickSurveyForm context={{ type: QuickSurveyType.FEATURE_FLAG, flag: mockFlag }} />)

        await userEvent.click(screen.getByRole('button', { name: /create & launch/i }))

        await waitFor(() => {
            expect(capturedRequest).not.toBeUndefined()
            expect(capturedRequest.linked_flag_id).toBe(1)
            expect(capturedRequest.questions[0].question).toBe(
                "You're trying our latest new feature. What do you think?"
            )
            expect(capturedRequest.start_date).not.toBeUndefined()
        })
    })

    it('sends correct payload for funnel survey', async () => {
        let capturedRequest: any
        useMocks({
            post: {
                '/api/projects/:team_id/surveys': async (req) => {
                    capturedRequest = await req.json()
                    return [200, { id: 'new-survey' }]
                },
            },
        })

        render(<QuickSurveyForm context={{ type: QuickSurveyType.FUNNEL, funnel: mockFunnel }} />)

        await userEvent.click(screen.getByRole('button', { name: /create & launch/i }))

        await waitFor(() => {
            expect(capturedRequest).not.toBeUndefined()
            expect(capturedRequest.linked_flag_id).toBeUndefined()
            expect(capturedRequest.conditions.events.values).toEqual([
                { name: 'step_one', propertyFilters: { url: { values: ['/checkout'], operator: 'exact' } } },
            ])
            expect(capturedRequest.appearance.surveyPopupDelaySeconds).toBe(15)
        })
    })
})

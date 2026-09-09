import { cleanup, fireEvent, render } from '@testing-library/react'
import posthog, { DisplaySurveyType, type Properties } from 'posthog-js'

import { FeedbackSurveyButton } from './FeedbackSurveyButton'

const SURVEY_ID = '018bcec8-6cf5-0000-c724-a51a86a4e8b1'

type SurveysLoadedCallback = (surveys: unknown[], context: { isLoaded: boolean }) => void

function mockSurveysLoaded(context: { isLoaded: boolean } | null): void {
    jest.mocked(posthog.onSurveysLoaded).mockImplementation(((cb: SurveysLoadedCallback) => {
        if (context) {
            cb([], context)
        }
        return () => {}
    }) as typeof posthog.onSurveysLoaded)
}

function renderButton(properties?: Properties): HTMLElement {
    const { getByRole } = render(<FeedbackSurveyButton surveyId={SURVEY_ID} properties={properties} />)
    return getByRole('button')
}

describe('FeedbackSurveyButton', () => {
    beforeEach(() => {
        jest.mocked(posthog.displaySurvey).mockClear()
    })

    afterEach(cleanup)

    it('is disabled and does not display the survey before the surveys extension reports in', () => {
        mockSurveysLoaded(null)
        const button = renderButton()

        expect(button.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(button)
        expect(posthog.displaySurvey).not.toHaveBeenCalled()
    })

    it('displays the survey with condition bypass once surveys load', () => {
        mockSurveysLoaded({ isLoaded: true })
        const properties = { feedback_surface: 'mcp_analytics', mcp_analytics_tab: 'activity' }
        const button = renderButton(properties)

        expect(button.getAttribute('aria-disabled')).not.toBe('true')
        fireEvent.click(button)
        expect(posthog.displaySurvey).toHaveBeenCalledWith(SURVEY_ID, {
            displayType: DisplaySurveyType.Popover,
            ignoreConditions: true,
            ignoreDelay: true,
            properties,
        })
    })

    it('stays disabled when the surveys extension reports a failed load', () => {
        mockSurveysLoaded({ isLoaded: false })
        const button = renderButton()

        expect(button.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(button)
        expect(posthog.displaySurvey).not.toHaveBeenCalled()
    })
})

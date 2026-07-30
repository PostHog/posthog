import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NEW_SURVEY } from 'scenes/surveys/constants'

import { initKeaTests } from '~/test/init'
import { Survey, SurveySchedule } from '~/types'

import { SuccessStep } from './SuccessStep'

jest.mock('../../SurveyAppearancePreview', () => ({
    SurveyAppearancePreview: () => <div data-testid="survey-preview" />,
}))

const createLaunchedSurvey = (overrides: Partial<Survey>): Survey =>
    ({ ...NEW_SURVEY, id: 'test-survey', ...overrides }) as Survey

describe('SuccessStep', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('summarizes frequency as event-driven when the survey repeats on every event', () => {
        render(
            <SuccessStep
                survey={createLaunchedSurvey({
                    conditions: {
                        actions: null,
                        events: { values: [{ name: 'payment_completed' }], repeatedActivation: true },
                    },
                    // Stored cadence left over from a template — must not be presented as the effective frequency
                    schedule: SurveySchedule.Recurring,
                    iteration_count: 10,
                    iteration_frequency_days: 30,
                })}
            />
        )

        expect(screen.getByText('Every time a trigger event is captured')).toBeInTheDocument()
        expect(screen.queryByText(/Up to 10 times/)).not.toBeInTheDocument()
    })

    it('summarizes the stored cadence when the survey does not repeat on events', () => {
        render(
            <SuccessStep
                survey={createLaunchedSurvey({
                    schedule: SurveySchedule.Recurring,
                    iteration_count: 2,
                    iteration_frequency_days: 90,
                })}
            />
        )

        expect(screen.getByText('Up to 2 times, every 90 days from launch')).toBeInTheDocument()
    })
})

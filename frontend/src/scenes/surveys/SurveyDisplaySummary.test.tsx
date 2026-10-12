import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SurveySchedule } from '~/types'

import { NEW_SURVEY } from './constants'
import { SurveyDisplaySummary } from './Survey'

describe('SurveyDisplaySummary', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a once schedule', SurveySchedule.Once, false, undefined, 'once per user'],
        ['repeated activation', SurveySchedule.Once, true, undefined, 'every time they occur'],
        ['an always schedule', SurveySchedule.Always, false, undefined, 'every time they occur'],
        [
            'an always schedule with a wait period',
            SurveySchedule.Always,
            false,
            7,
            'every time they occur, at most once every 7 days',
        ],
    ])(
        'describes the event trigger frequency for %s',
        (_name, schedule, repeatedActivation, seenSurveyWaitPeriodInDays, expectedFrequency) => {
            render(
                <SurveyDisplaySummary
                    id="new"
                    survey={{
                        ...NEW_SURVEY,
                        schedule,
                        conditions: {
                            actions: null,
                            events: { values: [{ name: 'signed_up' }], repeatedActivation },
                            seenSurveyWaitPeriodInDays,
                        },
                    }}
                />
            )

            expect(screen.getByText(expectedFrequency)).toBeInTheDocument()
        }
    )
})

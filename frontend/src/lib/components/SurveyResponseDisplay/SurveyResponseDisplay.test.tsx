import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { SurveyResponseDisplay } from './SurveyResponseDisplay'

describe('SurveyResponseDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders without mounting surveyLogic when $survey_id is missing', () => {
        render(
            <SurveyResponseDisplay
                eventProperties={{ $survey_name: 'Custom survey sent event', $survey_response: 'hello' }}
            />
        )

        expect(screen.getByText('Custom survey sent event')).toBeInTheDocument()
    })
})

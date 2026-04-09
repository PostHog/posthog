import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SurveyWizardComponent } from './SurveyWizard'

describe('SurveyWizard', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()

        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, {}],
            },
        })
    })

    it('keeps new surveys on template selection when full editor is preferred', async () => {
        initKeaTests()
        localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))

        router.actions.push('/surveys/guided/new')

        const replaceSpy = jest.fn()
        router.actions.replace = replaceSpy

        render(<SurveyWizardComponent id="new" />)

        await waitFor(() => {
            expect(screen.getByText('Choose a survey template')).toBeInTheDocument()
        })

        expect(replaceSpy).not.toHaveBeenCalled()
    })
})

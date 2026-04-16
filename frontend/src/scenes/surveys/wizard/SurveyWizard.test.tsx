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
        localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))

        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, {}],
            },
        })

        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps new surveys on template selection when full editor is preferred', async () => {
        router.actions.push('/surveys/guided/new')

        const replaceSpy = jest.spyOn(router.actions, 'replace').mockImplementation(() => {})

        render(<SurveyWizardComponent id="new" />)

        await waitFor(() => {
            expect(screen.getByText('Choose a survey template')).toBeInTheDocument()
        })

        expect(replaceSpy).not.toHaveBeenCalled()
    })
})

import { expectLogic } from 'kea-test-utils'

import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, Survey } from '~/types'

import { experimentFeedbackTabLogic } from './experimentFeedbackTabLogic'

const experiment = { id: 7, name: 'Checkout test', feature_flag: { id: 42, key: 'checkout-test' } } as Experiment
const linkedSurvey = { id: 'survey-1', name: 'Checkout feedback', linked_flag_id: 42 } as Survey

describe('experimentFeedbackTabLogic', () => {
    let surveyListRequests: URL[]
    let responseCountRequests: URL[]

    beforeEach(() => {
        initKeaTests()
        surveyListRequests = []
        responseCountRequests = []
        useMocks({
            get: {
                '/api/projects/:team/surveys/': ({ request }) => {
                    surveyListRequests.push(new URL(request.url))
                    return [200, { count: 1, results: [linkedSurvey], next: null, previous: null }]
                },
                '/api/projects/:team/surveys/responses_count': ({ request }) => {
                    responseCountRequests.push(new URL(request.url))
                    return [200, { 'survey-1': 3 }]
                },
            },
        })
    })

    it('loads only the surveys linked to the experiment flag and their response counts', async () => {
        const logic = experimentFeedbackTabLogic({ experiment })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        // The connected surveysLogic also lists surveys on mount, so look for the experiment-scoped request specifically
        expect(surveyListRequests.map((url) => url.searchParams.get('linked_flag_id'))).toContain('42')
        expect(logic.values.experimentSurveys).toEqual([linkedSurvey])
        expect(logic.values.experimentSurveysLoaded).toBe(true)
        expect(responseCountRequests.map((url) => url.searchParams.get('survey_ids'))).toContain('survey-1')
        expect(surveysLogic.values.surveysResponsesCount).toEqual({ 'survey-1': 3 })
    })
})

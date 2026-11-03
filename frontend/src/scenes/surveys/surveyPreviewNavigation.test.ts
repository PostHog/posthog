import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'

import { Survey, SurveyQuestionBranchingType } from '~/types'

import { getNextPreviewPageIndex } from './surveyPreviewNavigation'

describe('getNextPreviewPageIndex', () => {
    const buildSurvey = (displayThankYouMessage: boolean): Survey =>
        ({ questions: [{}, {}], appearance: { displayThankYouMessage } }) as Survey

    it.each([
        ['advances from the intro to question 0 without consulting branching', -1, true, undefined, 0],
        ['follows the branching result to the next question', 0, true, 1, 1],
        [
            'goes to the confirmation message when branching ends the survey',
            1,
            true,
            SurveyQuestionBranchingType.End,
            2,
        ],
        [
            'stays put when branching ends the survey and there is no confirmation',
            1,
            false,
            SurveyQuestionBranchingType.End,
            null,
        ],
    ] as const)('%s', (_name, pageIndex, displayThankYouMessage, nextStep, expected) => {
        jest.mocked(getNextSurveyStep).mockReturnValue(nextStep as any)

        expect(getNextPreviewPageIndex(buildSurvey(displayThankYouMessage), pageIndex, 'answer')).toBe(expected)
    })
})

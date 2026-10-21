import { Survey } from '~/types'

import { getHostedSurveyPageKind } from './hostedSurveyPageKind'

describe('getHostedSurveyPageKind', () => {
    it.each([
        ['intro page with the intro enabled', -1, { displayIntroScreen: true }, 'intro'],
        ['first question with the intro enabled', 0, { displayIntroScreen: true }, 'question'],
        ['intro index with the intro disabled', -1, { displayThankYouMessage: true }, 'question'],
        [
            'page after the last question with the confirmation enabled',
            2,
            { displayThankYouMessage: true },
            'confirmation',
        ],
        ['page after the last question with the confirmation disabled', 2, {}, 'question'],
    ] as const)('%s', (_name, pageIndex, appearance, expected) => {
        const survey = { questions: [{}, {}], appearance } as Survey

        expect(getHostedSurveyPageKind(survey, pageIndex)).toBe(expected)
    })
})

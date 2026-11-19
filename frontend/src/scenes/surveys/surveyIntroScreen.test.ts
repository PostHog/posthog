import { SurveyAppearance } from '~/types'

import { getIntroScreenDescriptionContentType, isIntroScreenShown } from './surveyIntroScreen'

describe('surveyIntroScreen', () => {
    describe('isIntroScreenShown', () => {
        it.each([
            ['no appearance', undefined, false],
            ['intro off with content', { displayIntroScreen: false, introScreenHeader: 'Welcome' }, false],
            ['intro on without content', { displayIntroScreen: true }, false],
            [
                'intro on with empty strings',
                { displayIntroScreen: true, introScreenHeader: '', introScreenDescription: '' },
                false,
            ],
            ['intro on with only a button text', { displayIntroScreen: true, introScreenButtonText: 'Go' }, false],
            ['intro on with a header', { displayIntroScreen: true, introScreenHeader: 'Welcome' }, true],
            ['intro on with a description', { displayIntroScreen: true, introScreenDescription: 'One minute' }, true],
        ] as [string, SurveyAppearance | undefined, boolean][])('%s', (_name, appearance, expected) => {
            expect(isIntroScreenShown(appearance)).toBe(expected)
        })
    })

    describe('getIntroScreenDescriptionContentType', () => {
        it.each([
            ['no appearance', undefined, 'html'],
            ['no content type', {}, 'html'],
            ['html', { introScreenDescriptionContentType: 'html' }, 'html'],
            ['text', { introScreenDescriptionContentType: 'text' }, 'text'],
        ] as [string, SurveyAppearance | undefined, string][])('%s', (_name, appearance, expected) => {
            expect(getIntroScreenDescriptionContentType(appearance)).toBe(expected)
        })
    })
})

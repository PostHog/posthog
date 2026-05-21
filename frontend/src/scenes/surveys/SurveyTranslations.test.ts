import { COMMON_LANGUAGES, COMMON_SURVEY_LANGUAGE_CODES, getSurveyLanguageLabel } from './SurveyTranslations'

describe('COMMON_LANGUAGES', () => {
    it('includes Romanian locale options', () => {
        expect(COMMON_LANGUAGES).toEqual(
            expect.arrayContaining([
                { value: 'ro', label: 'Romanian (ro)' },
                { value: 'ro-RO', label: 'Romanian - Romania (ro-RO)' },
            ])
        )
    })

    it('includes other common missing survey languages', () => {
        expect(COMMON_LANGUAGES).toEqual(
            expect.arrayContaining([
                { value: 'ca', label: 'Catalan (ca)' },
                { value: 'hr', label: 'Croatian (hr)' },
                { value: 'sr', label: 'Serbian (sr)' },
                { value: 'sl', label: 'Slovenian (sl)' },
                { value: 'et', label: 'Estonian (et)' },
                { value: 'lv', label: 'Latvian (lv)' },
                { value: 'lt', label: 'Lithuanian (lt)' },
            ])
        )
    })

    it.each([
        ['pt-BR', 'Portuguese - Brazil (pt-BR)'],
        ['ro-RO', 'Romanian - Romania (ro-RO)'],
        ['en-GB', 'English - UK (en-GB)'],
        ['zh-CN', 'Chinese - Simplified (zh-CN)'],
    ])('generates locale label %s as %s', (code, expected) => {
        expect(getSurveyLanguageLabel(code)).toBe(expected)
    })

    it('does not include duplicate language values', () => {
        const values = COMMON_LANGUAGES.map(({ value }) => value)

        expect(new Set(values).size).toBe(values.length)
        expect(new Set(COMMON_SURVEY_LANGUAGE_CODES).size).toBe(COMMON_SURVEY_LANGUAGE_CODES.length)
    })
})

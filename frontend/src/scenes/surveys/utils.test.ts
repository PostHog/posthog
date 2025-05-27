import { SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import { EventPropertyFilter, PropertyFilterType, Survey, SurveyAppearance } from '~/types'

import {
    calculateNpsBreakdown,
    createAnswerFilterHogQLExpression,
    sanitizeColor,
    sanitizeSurveyAppearance,
    validateColor,
} from './utils'

describe('survey utils', () => {
    beforeAll(() => {
        // Mock CSS.supports
        global.CSS = {
            supports: (property: string, value: string): boolean => {
                // Basic color validation - this is a simplified version
                if (property === 'color') {
                    // Helper to validate RGB/HSL number ranges
                    const isValidRGBNumber = (n: string): boolean => {
                        const num = parseInt(n)
                        return !isNaN(num) && num >= 0 && num <= 255
                    }

                    const isValidAlpha = (n: string): boolean => {
                        const num = parseFloat(n)
                        return !isNaN(num) && num >= 0 && num <= 1
                    }

                    // Hex colors (3, 4, 6 or 8 digits)
                    if (value.match(/^#([0-9A-Fa-f]{3}){1,2}$/) || value.match(/^#([0-9A-Fa-f]{4}){1,2}$/)) {
                        return true
                    }

                    // RGB colors
                    const rgbMatch = value.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/)
                    if (rgbMatch) {
                        return (
                            isValidRGBNumber(rgbMatch[1]) &&
                            isValidRGBNumber(rgbMatch[2]) &&
                            isValidRGBNumber(rgbMatch[3])
                        )
                    }

                    // RGBA colors
                    const rgbaMatch = value.match(/^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/)
                    if (rgbaMatch) {
                        return (
                            isValidRGBNumber(rgbaMatch[1]) &&
                            isValidRGBNumber(rgbaMatch[2]) &&
                            isValidRGBNumber(rgbaMatch[3]) &&
                            isValidAlpha(rgbaMatch[4])
                        )
                    }

                    // HSL colors
                    if (value.match(/^hsl\(\s*\d+\s*,\s*\d+%\s*,\s*\d+%\s*\)$/)) {
                        return true
                    }

                    // HSLA colors
                    if (value.match(/^hsla\(\s*\d+\s*,\s*\d+%\s*,\s*\d+%\s*,\s*[\d.]+\s*\)$/)) {
                        return true
                    }

                    // Named colors - extend the list with more common colors
                    return ['red', 'blue', 'green', 'transparent', 'black', 'white'].includes(value)
                }
                return false
            },
        } as unknown as typeof CSS
    })

    describe('validateColor', () => {
        it('returns undefined for valid colors in different formats', () => {
            // Hex colors
            expect(validateColor('#ff0000', 'test')).toBeUndefined()
            expect(validateColor('#f00', 'test')).toBeUndefined()
            expect(validateColor('#ff000080', 'test')).toBeUndefined() // With alpha

            // RGB/RGBA colors
            expect(validateColor('rgb(255, 0, 0)', 'test')).toBeUndefined()
            expect(validateColor('rgba(255, 0, 0, 0.5)', 'test')).toBeUndefined()

            // HSL/HSLA colors
            expect(validateColor('hsl(0, 100%, 50%)', 'test')).toBeUndefined()
            expect(validateColor('hsla(0, 100%, 50%, 0.5)', 'test')).toBeUndefined()

            // Named colors
            expect(validateColor('red', 'test')).toBeUndefined()
            expect(validateColor('transparent', 'test')).toBeUndefined()
        })

        it('returns error message for invalid colors', () => {
            expect(validateColor('not-a-color', 'test')).toBe(
                'Invalid color value for test. Please use a valid CSS color.'
            )
        })

        it('returns undefined for undefined input', () => {
            expect(validateColor(undefined, 'test')).toBeUndefined()
        })
    })

    describe('sanitizeColor', () => {
        it('returns undefined for falsy values', () => {
            expect(sanitizeColor(undefined)).toBeUndefined()
            expect(sanitizeColor('')).toBeUndefined()
        })

        it('adds # prefix to valid hex colors without it', () => {
            expect(sanitizeColor('ff0000')).toBe('#ff0000')
            expect(sanitizeColor('123456')).toBe('#123456')
        })

        it('returns original value for already valid colors', () => {
            expect(sanitizeColor('#ff0000')).toBe('#ff0000')
            expect(sanitizeColor('rgb(255, 0, 0)')).toBe('rgb(255, 0, 0)')
            expect(sanitizeColor('red')).toBe('red')
        })
    })

    describe('sanitizeSurveyAppearance', () => {
        it('returns null for null input', () => {
            expect(sanitizeSurveyAppearance(null)).toBeNull()
        })

        it('sanitizes all color fields in the appearance object', () => {
            const input: SurveyAppearance = {
                backgroundColor: 'ff0000',
                borderColor: '00ff00',
                ratingButtonActiveColor: '0000ff',
                ratingButtonColor: 'ffffff',
                submitButtonColor: '000000',
                submitButtonTextColor: 'cccccc',
                // Add other required fields from SurveyAppearance type as needed
            }

            const result = sanitizeSurveyAppearance(input)

            expect(result?.backgroundColor).toBe('#ff0000')
            expect(result?.borderColor).toBe('#00ff00')
            expect(result?.ratingButtonActiveColor).toBe('#0000ff')
            expect(result?.ratingButtonColor).toBe('#ffffff')
            expect(result?.submitButtonColor).toBe('#000000')
            expect(result?.submitButtonTextColor).toBe('#cccccc')
        })
    })

    describe('calculateNpsBreakdown', () => {
        it('returns all zeros when surveyRatingResults is empty', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [],
                total: 0,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toBeNull()
        })

        it('returns all zeros when data array is missing', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [],
                total: 0,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toBeNull()
        })

        it('returns all zeros when data array has incorrect length', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [1, 2, 3], // Less than 11 elements
                total: 6,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toBeNull()
        })

        it('returns early with all zeros when total is 0', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0], // despite having some counts in data
                total: 0, // total is explicitly 0
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 0,
                passives: 0,
                promoters: 0,
                score: '0.0',
                total: 0,
            })
        })

        it('correctly calculates NPS breakdown with all categories present', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [
                    1,
                    1,
                    1,
                    1,
                    1,
                    1,
                    1, // 7 detractors (0-6)
                    2,
                    2, // 4 passives (7-8)
                    3,
                    3,
                ], // 6 promoters (9-10)
                total: 17,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 7,
                passives: 4,
                promoters: 6,
                score: '-5.9',
                total: 17,
            })
        })

        it('handles all zeros', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                total: 0,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 0,
                passives: 0,
                promoters: 0,
                score: '0.0',
                total: 0,
            })
        })

        it('handles only promoters', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 5, 5], // only 9s and 10s
                total: 10,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 0,
                passives: 0,
                promoters: 10,
                score: '100.0',
                total: 10,
            })
        })

        it('handles only passives', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [0, 0, 0, 0, 0, 0, 0, 5, 5, 0, 0], // only 7s and 8s
                total: 10,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 0,
                passives: 10,
                promoters: 0,
                score: '0.0',
                total: 10,
            })
        })

        it('handles only detractors', () => {
            const surveyResults: SurveyRatingResults[number] = {
                data: [2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0], // only 0-6
                total: 14,
            }

            const result = calculateNpsBreakdown(surveyResults)

            expect(result).toEqual({
                detractors: 14,
                passives: 0,
                promoters: 0,
                score: '-100.0',
                total: 14,
            })
        })
    })
})

describe('createAnswerFilterHogQLExpression', () => {
    const mockSurvey = {
        questions: [{ id: 'q1' }, { id: 'q2' }, { id: 'q3' }],
    } as any as Survey

    it('returns empty string for empty filters array', () => {
        expect(createAnswerFilterHogQLExpression([], mockSurvey)).toBe('')
    })

    it('returns empty string for null or undefined filters', () => {
        expect(createAnswerFilterHogQLExpression(null as any, mockSurvey)).toBe('')
        expect(createAnswerFilterHogQLExpression(undefined as any, mockSurvey)).toBe('')
    })

    it('handles single exact filter', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'yes', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = 'yes')`)
    })

    it('handles filter for a different question', () => {
        const filters = [
            { key: '$survey_response_q2', value: 'no', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(1, 'q2') = 'no')`)
    })

    it('skips filters with empty values', () => {
        const filters = [
            { key: '$survey_response_q1', value: '', operator: 'exact', type: PropertyFilterType.Event },
            { key: '$survey_response_q2', value: null, operator: 'exact', type: PropertyFilterType.Event },
            { key: '$survey_response_q3', value: undefined, operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        expect(createAnswerFilterHogQLExpression(filters, mockSurvey)).toBe('')
    })

    it('skips filters with empty arrays', () => {
        const filters = [
            { key: '$survey_response_q1', value: [], operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        expect(createAnswerFilterHogQLExpression(filters, mockSurvey)).toBe('')
    })

    it('skips icontains filters with empty search patterns', () => {
        const filters = [
            { key: '$survey_response_q1', value: '%', operator: 'icontains', type: PropertyFilterType.Event },
            { key: '$survey_response_q2', value: '%%', operator: 'icontains', type: PropertyFilterType.Event },
            { key: '$survey_response_q3', value: '   ', operator: 'icontains', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        expect(createAnswerFilterHogQLExpression(filters, mockSurvey)).toBe('')
    })

    it('handles exact operator with single value', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'test', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = 'test')`)
    })

    it('handles exact operator with array values', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: ['option1', 'option2'],
                operator: 'exact',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') IN ('option1', 'option2'))`)
    })

    it('handles is_not operator with single value', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'test', operator: 'is_not', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') != 'test')`)
    })

    it('handles is_not operator with array values', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: ['option1', 'option2'],
                operator: 'is_not',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') NOT IN ('option1', 'option2'))`)
    })

    it('handles icontains operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'search', operator: 'icontains', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') ILIKE '%search%')`)
    })

    it('handles not_icontains operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'search', operator: 'not_icontains', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (NOT getSurveyResponse(0, 'q1') ILIKE '%search%')`)
    })

    it('handles regex operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: '.*test.*', operator: 'regex', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (match(getSurveyResponse(0, 'q1'), '.*test.*'))`)
    })

    it('handles not_regex operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: '.*test.*', operator: 'not_regex', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (NOT match(getSurveyResponse(0, 'q1'), '.*test.*'))`)
    })

    it('combines multiple filters with AND', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'yes', operator: 'exact', type: PropertyFilterType.Event },
            { key: '$survey_response_q2', value: 'no', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = 'yes') AND (getSurveyResponse(1, 'q2') = 'no')`)
    })

    it('skips filters with invalid question keys', () => {
        const filters = [
            { key: '$survey_response_invalid', value: 'test', operator: 'exact', type: PropertyFilterType.Event },
            { key: '$survey_response_q4', value: 'test2', operator: 'exact', type: PropertyFilterType.Event }, // q4 doesn't exist in mockSurvey
        ] as EventPropertyFilter[]

        expect(createAnswerFilterHogQLExpression(filters, mockSurvey)).toBe('')
    })

    it('handles array values for regex and not_regex operators', () => {
        const filters = [
            { key: '$survey_response_q1', value: ['.*pattern.*'], operator: 'regex', type: PropertyFilterType.Event },
            {
                key: '$survey_response_q2',
                value: ['.*pattern.*'],
                operator: 'not_regex',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(
            `AND (match(getSurveyResponse(0, 'q1'), '.*pattern.*')) AND (NOT match(getSurveyResponse(1, 'q2'), '.*pattern.*'))`
        )
    })

    it('handles array values for icontains operator', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: ['searchterm'],
                operator: 'icontains',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') ILIKE '%searchterm%')`)
    })

    it('handles unsupported operators', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: "O'Reilly",
                operator: 'exact',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = 'O\\'Reilly')`)
    })

    it('escapes backslashes in values', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: 'C:\\\\path\\\\to\\\\file',
                operator: 'exact',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = 'C:\\\\\\\\path\\\\\\\\to\\\\\\\\file')`)
    })

    it('escapes SQL injection attempts in array values', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: ['normal', "'; DROP TABLE users; --", "Robert'); DROP TABLE students; --"],
                operator: 'exact',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(
            `AND (getSurveyResponse(0, 'q1') IN ('normal', '\\'; DROP TABLE users; --', 'Robert\\'); DROP TABLE students; --'))`
        )
    })

    it('escapes complex SQL injection patterns', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: "' UNION SELECT * FROM users; --",
                operator: 'exact',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (getSurveyResponse(0, 'q1') = '\\' UNION SELECT * FROM users; --')`)
    })

    it('handles regex patterns with special characters', () => {
        const filters = [
            {
                key: '$survey_response_q1',
                value: ".*'; DROP TABLE.*",
                operator: 'regex',
                type: PropertyFilterType.Event,
            },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (match(getSurveyResponse(0, 'q1'), '.*\\'; DROP TABLE.*'))`)
    })
})

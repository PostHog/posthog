import { SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import {
    EventPropertyFilter,
    PropertyFilterType,
    Survey,
    SurveyAppearance,
    SurveyDisplayConditions,
    SurveyQuestionType,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

import {
    buildSurveyTimestampFilter,
    calculateNpsBreakdown,
    createAnswerFilterHogQLExpression,
    getSurveyEndDateForQuery,
    getSurveyResponse,
    getSurveyStartDateForQuery,
    sanitizeColor,
    sanitizeSurvey,
    sanitizeSurveyAppearance,
    sanitizeSurveyDisplayConditions,
    validateCSSProperty,
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
            expect(validateCSSProperty('color', '#ff0000')).toBeUndefined()
            expect(validateCSSProperty('color', '#f00')).toBeUndefined()
            expect(validateCSSProperty('color', '#ff000080')).toBeUndefined() // With alpha

            // RGB/RGBA colors
            expect(validateCSSProperty('color', 'rgb(255, 0, 0)')).toBeUndefined()
            expect(validateCSSProperty('color', 'rgba(255, 0, 0, 0.5)')).toBeUndefined()

            // HSL/HSLA colors
            expect(validateCSSProperty('color', 'hsl(0, 100%, 50%)')).toBeUndefined()
            expect(validateCSSProperty('color', 'hsla(0, 100%, 50%, 0.5)')).toBeUndefined()

            // Named colors
            expect(validateCSSProperty('color', 'red')).toBeUndefined()
            expect(validateCSSProperty('color', 'transparent')).toBeUndefined()
        })

        it('returns error message for invalid colors', () => {
            expect(validateCSSProperty('color', 'not-a-color')).toBe('not-a-color is not a valid property for color.')
        })

        it('returns undefined for undefined input', () => {
            expect(validateCSSProperty('color', undefined)).toBeUndefined()
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

        it('removes surveyPopupDelaySeconds for external surveys', () => {
            const input: SurveyAppearance = {
                backgroundColor: '#ffffff',
                surveyPopupDelaySeconds: 5,
                submitButtonColor: '#000000',
            }

            const result = sanitizeSurveyAppearance(input, false, SurveyType.ExternalSurvey)

            expect(result?.backgroundColor).toBe('#ffffff')
            expect(result?.submitButtonColor).toBe('#000000')
            expect(result?.surveyPopupDelaySeconds).toBeUndefined()
        })

        it('preserves surveyPopupDelaySeconds for non-external surveys', () => {
            const input: SurveyAppearance = {
                backgroundColor: '#ffffff',
                surveyPopupDelaySeconds: 5,
                submitButtonColor: '#000000',
            }

            const result = sanitizeSurveyAppearance(input, false, SurveyType.Popover)

            expect(result?.backgroundColor).toBe('#ffffff')
            expect(result?.submitButtonColor).toBe('#000000')
            expect(result?.surveyPopupDelaySeconds).toBe(5)
        })
    })

    describe('sanitizeSurveyDisplayConditions', () => {
        it('returns null for null input with non-external survey', () => {
            expect(sanitizeSurveyDisplayConditions(null, SurveyType.Popover)).toBeNull()
        })

        it('returns empty conditions object for external surveys with populated input', () => {
            const input: SurveyDisplayConditions = {
                url: 'https://example.com',
                actions: { values: [{ id: 123, name: 'test' }] },
                deviceTypes: ['mobile'],
                seenSurveyWaitPeriodInDays: 7,
                events: { values: [{ name: 'test' }] },
            }

            const result = sanitizeSurveyDisplayConditions(input, SurveyType.ExternalSurvey)

            expect(result).toEqual({
                actions: { values: [] },
                events: { values: [] },
                deviceTypes: undefined,
                deviceTypesMatchType: undefined,
                linkedFlagVariant: undefined,
                seenSurveyWaitPeriodInDays: undefined,
                url: undefined,
                urlMatchType: undefined,
            })
        })

        it('preserves conditions for non-external surveys', () => {
            const input: SurveyDisplayConditions = {
                url: 'https://example.com',
                actions: { values: [{ id: 123, name: 'test' }] },
                events: { values: [{ name: 'test' }] },
                deviceTypes: ['mobile'],
            }

            const result = sanitizeSurveyDisplayConditions(input, SurveyType.Popover)

            expect(result?.url).toBe('https://example.com')
            expect(result?.actions).toEqual({ values: [{ id: 123, name: 'test' }] })
            expect(result?.events).toEqual({ values: [{ name: 'test' }] })
            expect(result?.deviceTypes).toEqual(['mobile'])
        })
    })

    describe('sanitizeSurvey', () => {
        it('sanitizes external survey by removing prohibited fields', () => {
            const inputSurvey = {
                type: SurveyType.ExternalSurvey,
                name: 'Test External Survey',
                questions: [],
                linked_flag_id: 123,
                targeting_flag_filters: { groups: [{ rollout_percentage: 50 }] },
                conditions: {
                    url: 'https://example.com',
                    actions: { values: [{ id: 123, name: 'test' }] },
                    events: { values: [{ name: 'test' }] },
                },
                appearance: {
                    backgroundColor: '#ffffff',
                    surveyPopupDelaySeconds: 5,
                    submitButtonColor: '#000000',
                },
            }

            const result = sanitizeSurvey(inputSurvey)

            // Should remove prohibited fields
            expect(result.linked_flag_id).toBeNull()
            expect(result.targeting_flag_filters).toBeUndefined()
            expect(result.remove_targeting_flag).toBe(true)

            // Should sanitize conditions to empty values
            expect(result.conditions).toEqual({
                actions: { values: [] },
                events: { values: [] },
                deviceTypes: undefined,
                deviceTypesMatchType: undefined,
                linkedFlagVariant: undefined,
                seenSurveyWaitPeriodInDays: undefined,
                url: undefined,
                urlMatchType: undefined,
            })

            // Should remove surveyPopupDelaySeconds from appearance
            expect(result.appearance?.surveyPopupDelaySeconds).toBeUndefined()
            expect(result.appearance?.backgroundColor).toBe('#ffffff')
            expect(result.appearance?.submitButtonColor).toBe('#000000')
        })

        it('preserves fields for non-external surveys', () => {
            const inputSurvey = {
                type: SurveyType.Popover,
                name: 'Test Popover Survey',
                questions: [],
                linked_flag_id: 123,
                targeting_flag_filters: { groups: [{ rollout_percentage: 50 }] },
                conditions: {
                    url: 'https://example.com',
                    actions: { values: [{ id: 123, name: 'test' }] },
                    events: { values: [{ name: 'test' }] },
                },
                appearance: {
                    backgroundColor: '#ffffff',
                    surveyPopupDelaySeconds: 5,
                    submitButtonColor: '#000000',
                },
            }

            const result = sanitizeSurvey(inputSurvey)

            // Should preserve all fields for non-external surveys
            expect(result.linked_flag_id).toBe(123)
            expect(result.targeting_flag_filters).toEqual({ groups: [{ rollout_percentage: 50 }] })
            expect(result.remove_targeting_flag).toBeUndefined()

            // Should preserve conditions
            expect(result.conditions?.url).toBe('https://example.com')
            expect(result.conditions?.actions).toEqual({ values: [{ id: 123, name: 'test' }] })
            expect(result.conditions?.events).toEqual({ values: [{ name: 'test' }] })

            // Should preserve surveyPopupDelaySeconds
            expect(result.appearance?.surveyPopupDelaySeconds).toBe(5)
            expect(result.appearance?.backgroundColor).toBe('#ffffff')
            expect(result.appearance?.submitButtonColor).toBe('#000000')
        })

        it('removes widget-specific fields for non-widget surveys', () => {
            const inputSurvey: Partial<Survey> = {
                type: SurveyType.Popover,
                name: 'Test Survey',
                questions: [],
                appearance: {
                    backgroundColor: '#ffffff',
                    widgetType: SurveyWidgetType.Tab,
                    widgetLabel: 'Feedback',
                    widgetColor: '#ff0000',
                },
            }

            const result = sanitizeSurvey(inputSurvey)

            // Should remove widget-specific fields for non-widget surveys
            expect(result.appearance?.backgroundColor).toBe('#ffffff')
            expect(result.appearance).not.toHaveProperty('widgetType')
            expect(result.appearance).not.toHaveProperty('widgetLabel')
            expect(result.appearance).not.toHaveProperty('widgetColor')
        })

        it('removing conditions object makes it go back to the empty conditions object', () => {
            const inputSurvey = {
                type: SurveyType.ExternalSurvey,
                name: 'Test Survey',
                questions: [],
                conditions: {
                    actions: { values: [] },
                    events: { values: [] },
                },
            }

            const result = sanitizeSurvey(inputSurvey)

            // Should remove empty conditions object
            expect(result.conditions).toEqual({
                actions: {
                    values: [],
                },
                events: {
                    values: [],
                },
                deviceTypes: undefined,
                deviceTypesMatchType: undefined,
                linkedFlagVariant: undefined,
                seenSurveyWaitPeriodInDays: undefined,
                url: undefined,
                urlMatchType: undefined,
            })
        })

        it('Remove conditions key if its value is null', () => {
            const inputSurvey = {
                type: SurveyType.ExternalSurvey,
                name: 'Test Survey',
                questions: [],
                conditions: null,
            }

            const result = sanitizeSurvey(inputSurvey)

            expect(result.conditions).toBeUndefined()
        })

        it('Keep conditions key even if its value is null when option is present', () => {
            const inputSurvey = {
                type: SurveyType.ExternalSurvey,
                name: 'Test Survey',
                questions: [],
                conditions: null,
            }

            const result = sanitizeSurvey(inputSurvey, { keepEmptyConditions: true })

            expect(result.conditions).toBeNull()
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

    describe('buildSurveyTimestampFilter', () => {
        it('uses survey default dates when no date range provided', () => {
            const survey = { created_at: '2024-08-27T15:30:00Z', end_date: '2024-08-30T10:00:00Z' }
            const result = buildSurveyTimestampFilter(survey)

            expect(result).toBe(`AND timestamp >= '2024-08-27T00:00:00'
        AND timestamp <= '2024-08-30T23:59:59'`)
        })

        it('respects user date range when provided', () => {
            const survey = { created_at: '2024-08-27T15:30:00Z', end_date: '2024-08-30T10:00:00Z' }
            const dateRange = { date_from: '2024-08-28', date_to: '2024-08-29' }
            const result = buildSurveyTimestampFilter(survey, dateRange)

            expect(result).toBe(`AND timestamp >= '2024-08-28T00:00:00'
    AND timestamp <= '2024-08-29T23:59:59'`)
        })

        it('enforces survey creation date as minimum even with earlier user date', () => {
            const survey = { created_at: '2024-08-27T15:30:00Z', end_date: null }
            const dateRange = { date_from: '2024-08-25', date_to: '2024-08-29' } // Earlier than survey creation
            const result = buildSurveyTimestampFilter(survey, dateRange)

            expect(result).toContain(`timestamp >= '2024-08-27T00:00:00'`) // Should use survey start, not user's earlier date
        })

        it('handles timezone consistency across different user timezones', () => {
            const timezones = [0, 180, -480] // UTC, GMT-3, GMT+8

            timezones.forEach((offset) => {
                const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset
                Date.prototype.getTimezoneOffset = jest.fn(() => offset)

                try {
                    const survey = { created_at: '2024-08-27T15:30:00Z', end_date: '2024-08-30T10:00:00Z' }
                    const dateRange = { date_from: '2024-08-28T12:00:00Z', date_to: '2024-08-29T12:00:00Z' }
                    const result = buildSurveyTimestampFilter(survey, dateRange)

                    // All timezones should produce the same result
                    expect(result).toBe(`AND timestamp >= '2024-08-28T00:00:00'
    AND timestamp <= '2024-08-29T23:59:59'`)
                } finally {
                    Date.prototype.getTimezoneOffset = originalGetTimezoneOffset
                }
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = 'yes')`)
    })

    it('handles filter for a different question', () => {
        const filters = [
            { key: '$survey_response_q2', value: 'no', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[1], 1)} = 'no')`)
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = 'test')`)
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} IN ('option1', 'option2'))`)
    })

    it('handles is_not operator with single value', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'test', operator: 'is_not', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} != 'test')`)
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} NOT IN ('option1', 'option2'))`)
    })

    it('handles icontains operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'search', operator: 'icontains', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} ILIKE '%search%')`)
    })

    it('handles not_icontains operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'search', operator: 'not_icontains', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (NOT ${getSurveyResponse(mockSurvey.questions[0], 0)} ILIKE '%search%')`)
    })

    it('handles regex operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: '.*test.*', operator: 'regex', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (match(${getSurveyResponse(mockSurvey.questions[0], 0)}, '.*test.*'))`)
    })

    it('handles not_regex operator', () => {
        const filters = [
            { key: '$survey_response_q1', value: '.*test.*', operator: 'not_regex', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(`AND (NOT match(${getSurveyResponse(mockSurvey.questions[0], 0)}, '.*test.*'))`)
    })

    it('combines multiple filters with AND', () => {
        const filters = [
            { key: '$survey_response_q1', value: 'yes', operator: 'exact', type: PropertyFilterType.Event },
            { key: '$survey_response_q2', value: 'no', operator: 'exact', type: PropertyFilterType.Event },
        ] as EventPropertyFilter[]

        const result = createAnswerFilterHogQLExpression(filters, mockSurvey)
        expect(result).toBe(
            `AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = 'yes') AND (${getSurveyResponse(
                mockSurvey.questions[1],
                1
            )} = 'no')`
        )
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
            `AND (match(${getSurveyResponse(
                mockSurvey.questions[0],
                0
            )}, '.*pattern.*')) AND (NOT match(${getSurveyResponse(mockSurvey.questions[1], 1)}, '.*pattern.*'))`
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} ILIKE '%searchterm%')`)
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
        expect(result).toBe(`AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = 'O\\'Reilly')`)
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
        expect(result).toBe(
            `AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = 'C:\\\\\\\\path\\\\\\\\to\\\\\\\\file')`
        )
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
            `AND (${getSurveyResponse(
                mockSurvey.questions[0],
                0
            )} IN ('normal', '\\'; DROP TABLE users; --', 'Robert\\'); DROP TABLE students; --'))`
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
        expect(result).toBe(
            `AND (${getSurveyResponse(mockSurvey.questions[0], 0)} = '\\' UNION SELECT * FROM users; --')`
        )
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
        expect(result).toBe(`AND (match(${getSurveyResponse(mockSurvey.questions[0], 0)}, '.*\\'; DROP TABLE.*'))`)
    })

    describe('multiple choice questions', () => {
        const surveyWithMultipleChoiceQuestion = {
            ...mockSurvey,
            questions: [
                {
                    ...mockSurvey.questions[0],
                    type: SurveyQuestionType.MultipleChoice,
                    choices: [
                        { id: 'c1', label: 'test' },
                        { id: 'c2', label: 'test2' },
                    ],
                },
            ],
        } as any as Survey

        it('handles icontains operator', () => {
            const filters = [
                { key: '$survey_response_q1', value: 'test', operator: 'icontains', type: PropertyFilterType.Event },
            ] as EventPropertyFilter[]

            const result = createAnswerFilterHogQLExpression(filters, surveyWithMultipleChoiceQuestion)
            expect(result).toBe(
                `AND (arrayExists(x -> x ilike '%test%', ${getSurveyResponse(surveyWithMultipleChoiceQuestion.questions[0], 0)}))`
            )
        })

        it('handles not_icontains operator for multiple choice question', () => {
            const filters = [
                {
                    key: '$survey_response_q1',
                    value: 'test',
                    operator: 'not_icontains',
                    type: PropertyFilterType.Event,
                },
            ] as EventPropertyFilter[]

            const result = createAnswerFilterHogQLExpression(filters, surveyWithMultipleChoiceQuestion)
            expect(result).toBe(
                `AND (NOT arrayExists(x -> x ilike '%test%', ${getSurveyResponse(surveyWithMultipleChoiceQuestion.questions[0], 0)}))`
            )
        })

        it('handles regex operator', () => {
            const filters = [
                { key: '$survey_response_q1', value: '.*test.*', operator: 'regex', type: PropertyFilterType.Event },
            ] as EventPropertyFilter[]

            const result = createAnswerFilterHogQLExpression(filters, surveyWithMultipleChoiceQuestion)
            expect(result).toBe(
                `AND (arrayExists(x -> match(x, '.*test.*'), ${getSurveyResponse(surveyWithMultipleChoiceQuestion.questions[0], 0)}))`
            )
        })

        it('handles not_regex operator', () => {
            const filters = [
                {
                    key: '$survey_response_q1',
                    value: '.*test.*',
                    operator: 'not_regex',
                    type: PropertyFilterType.Event,
                },
            ] as EventPropertyFilter[]

            const result = createAnswerFilterHogQLExpression(filters, surveyWithMultipleChoiceQuestion)
            expect(result).toBe(
                `AND (NOT arrayExists(x -> match(x, '.*test.*'), ${getSurveyResponse(surveyWithMultipleChoiceQuestion.questions[0], 0)}))`
            )
        })
    })
})

describe('timezone handling in survey date queries', () => {
    const createMockSurvey = (createdAt: string, endDate?: string): Pick<Survey, 'created_at' | 'end_date'> => ({
        created_at: createdAt,
        end_date: endDate || null,
    })

    describe('regression test for timezone parsing bug', () => {
        it('parses UTC dates correctly regardless of user timezone', () => {
            // Mock different timezones to ensure our fix works
            const timezones = [
                { name: 'UTC', offset: 0 },
                { name: 'GMT-3', offset: 180 },
                { name: 'GMT+8', offset: -480 },
            ]

            timezones.forEach(({ offset }) => {
                const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset
                Date.prototype.getTimezoneOffset = jest.fn(() => offset)

                try {
                    const survey = createMockSurvey('2024-08-27T15:30:00Z', '2024-08-30T10:00:00Z')

                    const startDate = getSurveyStartDateForQuery(survey)
                    const endDate = getSurveyEndDateForQuery(survey)

                    // All timezones should produce the same UTC results
                    expect(startDate).toBe('2024-08-27T00:00:00')
                    expect(endDate).toBe('2024-08-30T23:59:59')
                } finally {
                    Date.prototype.getTimezoneOffset = originalGetTimezoneOffset
                }
            })
        })

        it('handles null end_date correctly', () => {
            const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset
            Date.prototype.getTimezoneOffset = jest.fn(() => 180) // GMT-3

            try {
                const survey = createMockSurvey('2024-08-27T15:30:00Z')
                const result = getSurveyEndDateForQuery(survey)

                // Should use current day end, format should be consistent
                expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T23:59:59$/)
            } finally {
                Date.prototype.getTimezoneOffset = originalGetTimezoneOffset
            }
        })
    })
})

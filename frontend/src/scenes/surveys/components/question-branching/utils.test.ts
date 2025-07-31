import { SurveyQuestion, SurveyQuestionBranchingType, SurveyQuestionType } from '~/types'

import {
    SPECIFIC_QUESTION_SEPARATOR,
    branchingConfigToDropdownValue,
    canQuestionHaveResponseBasedBranching,
    createBranchingConfig,
    createSpecificQuestionValue,
    dropdownValueToBranchingConfig,
    getDefaultBranchingType,
    isSpecificQuestionValue,
    isValidBranchingType,
    parseSpecificQuestionValue,
} from './utils'

describe('branching utils', () => {
    describe('createSpecificQuestionValue', () => {
        it.each([
            [0, `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}0`],
            [5, `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}5`],
            [10, `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}10`],
        ])('creates correct specific question value format for index %i', (index, expected) => {
            expect(createSpecificQuestionValue(index)).toBe(expected)
        })
    })

    describe('parseSpecificQuestionValue', () => {
        it.each([
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}0`, 0],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}5`, 5],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}10`, 10],
        ])('parses valid specific question value %s to %i', (value, expected) => {
            expect(parseSpecificQuestionValue(value)).toBe(expected)
        })

        it.each([
            [SurveyQuestionBranchingType.End],
            [SurveyQuestionBranchingType.NextQuestion],
            ['invalid'],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}invalid`],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}`],
            [`${SurveyQuestionBranchingType.SpecificQuestion}`],
        ])('returns null for invalid value: %s', (invalidValue) => {
            expect(parseSpecificQuestionValue(invalidValue)).toBe(null)
        })
    })

    describe('isSpecificQuestionValue', () => {
        it.each([
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}0`, true],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}5`, true],
            [SurveyQuestionBranchingType.End, false],
            [SurveyQuestionBranchingType.NextQuestion, false],
            ['invalid', false],
            [`${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}invalid`, false],
        ])('correctly identifies %s as %s', (value, expected) => {
            expect(isSpecificQuestionValue(value)).toBe(expected)
        })
    })

    describe('getDefaultBranchingType', () => {
        it.each([
            [0, 3, SurveyQuestionBranchingType.NextQuestion],
            [1, 3, SurveyQuestionBranchingType.NextQuestion],
            [2, 3, SurveyQuestionBranchingType.End],
            [0, 1, SurveyQuestionBranchingType.End],
        ])('returns %s for question %i of %i total', (questionIndex, totalQuestions, expected) => {
            expect(getDefaultBranchingType(questionIndex, totalQuestions)).toBe(expected)
        })
    })

    describe('branchingConfigToDropdownValue', () => {
        it('handles SpecificQuestion type with index', () => {
            expect(branchingConfigToDropdownValue(SurveyQuestionBranchingType.SpecificQuestion, 5)).toBe(
                `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}5`
            )
        })

        it.each([
            [SurveyQuestionBranchingType.End],
            [SurveyQuestionBranchingType.NextQuestion],
            [SurveyQuestionBranchingType.ResponseBased],
        ])('handles %s branching type', (branchingType) => {
            expect(branchingConfigToDropdownValue(branchingType)).toBe(branchingType)
        })

        it('handles SpecificQuestion type without index', () => {
            expect(branchingConfigToDropdownValue(SurveyQuestionBranchingType.SpecificQuestion)).toBe(
                SurveyQuestionBranchingType.SpecificQuestion
            )
        })
    })

    describe('isValidBranchingType', () => {
        it.each([
            [SurveyQuestionBranchingType.NextQuestion, true],
            [SurveyQuestionBranchingType.End, true],
            [SurveyQuestionBranchingType.ResponseBased, true],
            [SurveyQuestionBranchingType.SpecificQuestion, true],
            ['invalid_type', false],
            ['', false],
            ['next_question_typo', false],
            ['123', false],
        ])('validates %s as %s', (value, expected) => {
            expect(isValidBranchingType(value)).toBe(expected)
        })
    })

    describe('dropdownValueToBranchingConfig', () => {
        it('parses specific question values correctly', () => {
            const result = dropdownValueToBranchingConfig(
                `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}5`
            )
            expect(result).toEqual({
                type: SurveyQuestionBranchingType.SpecificQuestion,
                specificQuestionIndex: 5,
            })
        })

        it.each([
            [SurveyQuestionBranchingType.End, { type: SurveyQuestionBranchingType.End }],
            [SurveyQuestionBranchingType.NextQuestion, { type: SurveyQuestionBranchingType.NextQuestion }],
            [SurveyQuestionBranchingType.ResponseBased, { type: SurveyQuestionBranchingType.ResponseBased }],
        ])('parses %s correctly', (branchingType, expected) => {
            expect(dropdownValueToBranchingConfig(branchingType)).toEqual(expected)
        })

        it('handles invalid branching type gracefully', () => {
            const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})

            const result = dropdownValueToBranchingConfig('invalid_type')

            expect(result).toEqual({
                type: SurveyQuestionBranchingType.NextQuestion,
            })
            expect(consoleSpy).toHaveBeenCalledWith(
                'Invalid branching type: invalid_type. Falling back to NextQuestion.'
            )

            consoleSpy.mockRestore()
        })

        it('handles empty string gracefully', () => {
            const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})

            const result = dropdownValueToBranchingConfig('')

            expect(result).toEqual({
                type: SurveyQuestionBranchingType.NextQuestion,
            })
            expect(consoleSpy).toHaveBeenCalledWith('Invalid branching type: . Falling back to NextQuestion.')

            consoleSpy.mockRestore()
        })
    })

    describe('canQuestionHaveResponseBasedBranching', () => {
        it.each([
            [
                'Rating',
                {
                    type: SurveyQuestionType.Rating,
                    question: 'Rate this',
                    description: '',
                    scale: 5,
                    display: 'number',
                    lowerBoundLabel: 'Low',
                    upperBoundLabel: 'High',
                } as SurveyQuestion,
                true,
            ],
            [
                'SingleChoice',
                {
                    type: SurveyQuestionType.SingleChoice,
                    question: 'Choose one',
                    description: '',
                    choices: ['Yes', 'No'],
                } as SurveyQuestion,
                true,
            ],
            [
                'Open',
                {
                    type: SurveyQuestionType.Open,
                    question: 'Tell us more',
                    description: '',
                } as SurveyQuestion,
                false,
            ],
            [
                'MultipleChoice',
                {
                    type: SurveyQuestionType.MultipleChoice,
                    question: 'Choose multiple',
                    description: '',
                    choices: ['A', 'B', 'C'],
                } as SurveyQuestion,
                false,
            ],
            [
                'Link',
                {
                    type: SurveyQuestionType.Link,
                    question: 'Click here',
                    description: '',
                    link: 'https://example.com',
                } as SurveyQuestion,
                false,
            ],
        ])('returns %s for %s questions', (_, question, expected) => {
            expect(canQuestionHaveResponseBasedBranching(question)).toBe(expected)
        })
    })

    describe('createBranchingConfig', () => {
        it('returns undefined for NextQuestion type', () => {
            expect(createBranchingConfig(SurveyQuestionBranchingType.NextQuestion)).toBeUndefined()
        })

        it.each([
            [SurveyQuestionBranchingType.End, undefined, { type: SurveyQuestionBranchingType.End }],
            [
                SurveyQuestionBranchingType.ResponseBased,
                undefined,
                { type: SurveyQuestionBranchingType.ResponseBased, responseValues: {} },
            ],
            [
                SurveyQuestionBranchingType.SpecificQuestion,
                5,
                { type: SurveyQuestionBranchingType.SpecificQuestion, index: 5 },
            ],
        ])('creates %s branching config', (branchingType, specificQuestionIndex, expected) => {
            expect(createBranchingConfig(branchingType, specificQuestionIndex)).toEqual(expected)
        })

        it('throws error for SpecificQuestion without index', () => {
            expect(() => createBranchingConfig(SurveyQuestionBranchingType.SpecificQuestion)).toThrow(
                'specificQuestionIndex is required for SpecificQuestion branching type'
            )
        })

        it('throws error for unknown branching type', () => {
            expect(() => createBranchingConfig('unknown' as SurveyQuestionBranchingType)).toThrow(
                'Unknown branching type: unknown'
            )
        })
    })

    describe('integration tests', () => {
        it('round-trip conversion works correctly', () => {
            // Test SpecificQuestion round-trip
            const specificQuestionValue = createSpecificQuestionValue(3)
            const parsedConfig = dropdownValueToBranchingConfig(specificQuestionValue)
            expect(parsedConfig).toEqual({
                type: SurveyQuestionBranchingType.SpecificQuestion,
                specificQuestionIndex: 3,
            })

            const backToValue = branchingConfigToDropdownValue(parsedConfig.type, parsedConfig.specificQuestionIndex)
            expect(backToValue).toBe(specificQuestionValue)

            // Test other types round-trip
            const endConfig = dropdownValueToBranchingConfig(SurveyQuestionBranchingType.End)
            expect(endConfig.type).toBe(SurveyQuestionBranchingType.End)
            expect(branchingConfigToDropdownValue(endConfig.type)).toBe(SurveyQuestionBranchingType.End)
        })

        it('createBranchingConfig works with dropdownValueToBranchingConfig', () => {
            // Test SpecificQuestion
            const specificConfig = dropdownValueToBranchingConfig(
                `${SurveyQuestionBranchingType.SpecificQuestion}${SPECIFIC_QUESTION_SEPARATOR}2`
            )
            const createdBranching = createBranchingConfig(specificConfig.type, specificConfig.specificQuestionIndex)
            expect(createdBranching).toEqual({
                type: SurveyQuestionBranchingType.SpecificQuestion,
                index: 2,
            })

            // Test End
            const endConfig = dropdownValueToBranchingConfig(SurveyQuestionBranchingType.End)
            const createdEndBranching = createBranchingConfig(endConfig.type)
            expect(createdEndBranching).toEqual({
                type: SurveyQuestionBranchingType.End,
            })
        })
    })
})

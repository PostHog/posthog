import { render } from '@testing-library/react'

import {
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
} from '~/types'

import {
    describeBranchingChanges,
    describeCommonChanges,
    describeFieldChange,
    describeLinkChanges,
    describeMultipleChoiceChanges,
    describeQuestionChanges,
    describeRatingChanges,
} from './surveyActivityDescriber'

const getTextContent = (jsxElement: JSX.Element): string => {
    const { container } = render(jsxElement)
    return container.textContent || ''
}

describe('describeFieldChange', () => {
    test('sets field with unit', () => {
        const result = describeFieldChange('wait period', null, 30, 'days')
        expect(getTextContent(result)).toBe('set wait period to 30 days')
    })

    test('removes field with unit', () => {
        const result = describeFieldChange('wait period', 30, null, 'days')
        expect(getTextContent(result)).toBe('removed wait period (was 30 days)')
    })

    test('changes field with unit', () => {
        const result = describeFieldChange('wait period', 30, 60, 'days')
        expect(getTextContent(result)).toBe('changed wait period from 30 days to 60 days')
    })

    test('sets field without unit', () => {
        const result = describeFieldChange('response limit', null, 100)
        expect(getTextContent(result)).toBe('set response limit to 100')
    })

    test('removes field without unit', () => {
        const result = describeFieldChange('response limit', 100, null)
        expect(getTextContent(result)).toBe('removed response limit (was 100)')
    })

    test('changes field without unit', () => {
        const result = describeFieldChange('response limit', 100, 200)
        expect(getTextContent(result)).toBe('changed response limit from 100 to 200')
    })

    test('handles undefined before value', () => {
        const result = describeFieldChange('iteration count', undefined, 5)
        expect(getTextContent(result)).toBe('set iteration count to 5')
    })

    test('handles undefined after value', () => {
        const result = describeFieldChange('iteration count', 5, undefined)
        expect(getTextContent(result)).toBe('removed iteration count (was 5)')
    })

    test('handles empty string before value', () => {
        const result = describeFieldChange('survey title', '', 'New Title')
        expect(getTextContent(result)).toBe('set survey title to New Title')
    })

    test('handles empty string after value', () => {
        const result = describeFieldChange('survey title', 'Old Title', '')
        expect(getTextContent(result)).toBe('removed survey title (was Old Title)')
    })

    test('handles both values as empty strings', () => {
        const result = describeFieldChange('survey title', '', '')
        expect(getTextContent(result)).toBe('')
    })

    test('handles before and after as identical', () => {
        const result = describeFieldChange('response limit', 100, 100)
        expect(getTextContent(result)).toBe('')
    })

    test('handles string values with unit', () => {
        const result = describeFieldChange('response time', 'fast', 'slow', 'seconds')
        expect(getTextContent(result)).toBe('changed response time from fast seconds to slow seconds')
    })

    test('handles boolean values', () => {
        const result = describeFieldChange('is active', false, true)
        expect(getTextContent(result)).toBe('changed is active from false to true')
    })

    test('handles null values', () => {
        const result = describeFieldChange('response limit', null, null)
        expect(getTextContent(result)).toBe('')
    })
})

describe('describeCommonChanges', () => {
    const before: SurveyQuestion = {
        question: 'What is your favorite color?',
        description: 'Choose a color',
        type: SurveyQuestionType.SingleChoice,
        optional: false,
        buttonText: 'Next',
        choices: ['Red', 'Blue', 'Green'],
    }
    const after: SurveyQuestion = {
        ...before,
        question: 'What is your favorite animal?',
        description: 'Choose an animal',
        optional: true,
        buttonText: 'Continue',
    }

    test('describes common changes', () => {
        const changes = describeCommonChanges(before, after)
        expect(changes).toHaveLength(4)
        expect(getTextContent(changes[0])).toBe(
            'changed question text from "What is your favorite color?" to "What is your favorite animal?"'
        )
        expect(getTextContent(changes[1])).toBe(
            'changed the question description from "Choose a color" to "Choose an animal"'
        )
        expect(getTextContent(changes[2])).toBe('made question optional')
        expect(getTextContent(changes[3])).toBe('changed button text from "Next" to "Continue"')
    })
})

describe('describeLinkChanges', () => {
    const before: LinkSurveyQuestion = {
        question: 'Visit our website',
        type: SurveyQuestionType.Link,
        link: 'http://example.com',
    }
    const after: LinkSurveyQuestion = {
        ...before,
        link: 'http://example.org',
    }

    test('describes link changes', () => {
        const changes = describeLinkChanges([before, after])
        expect(changes).toHaveLength(1)
        expect(getTextContent(changes[0])).toBe('updated link from http://example.com to http://example.org')
    })
})

describe('describeRatingChanges', () => {
    const before: RatingSurveyQuestion = {
        question: 'Rate our service',
        type: SurveyQuestionType.Rating,
        display: 'emoji',
        scale: 5,
        lowerBoundLabel: 'Poor',
        upperBoundLabel: 'Excellent',
    }
    const after: RatingSurveyQuestion = {
        ...before,
        display: 'number',
        scale: 10,
        lowerBoundLabel: 'Bad',
        upperBoundLabel: 'Good',
    }

    test('describes rating changes', () => {
        const changes = describeRatingChanges([before, after])
        expect(changes).toHaveLength(3)
        expect(getTextContent(changes[0])).toBe('changed rating display from emoji to number')
        expect(getTextContent(changes[1])).toBe('changed rating scale from 5 to 10')
        expect(getTextContent(changes[2])).toBe('updated rating labels from "Poor"-"Excellent" to "Bad"-"Good"')
    })
})

describe('describeMultipleChoiceChanges', () => {
    const before: MultipleSurveyQuestion = {
        question: 'Select your hobbies',
        type: SurveyQuestionType.MultipleChoice,
        choices: ['Reading', 'Traveling', 'Cooking'],
        shuffleOptions: false,
        hasOpenChoice: false,
    }
    const after: MultipleSurveyQuestion = {
        ...before,
        choices: ['Reading', 'Cooking', 'Gaming'],
        shuffleOptions: true,
        hasOpenChoice: true,
    }

    test('describes multiple choice changes', () => {
        const changes = describeMultipleChoiceChanges([before, after])
        expect(changes).toHaveLength(4)
        expect(getTextContent(changes[0])).toBe('added choices: Gaming')
        expect(getTextContent(changes[1])).toBe('removed choices: Traveling')
        expect(getTextContent(changes[2])).toBe('enabled option shuffling')
        expect(getTextContent(changes[3])).toBe('added open choice option')
    })
})

describe('describeBranchingChanges', () => {
    const before: MultipleSurveyQuestion = {
        question: 'Do you like ice cream?',
        type: SurveyQuestionType.SingleChoice,
        choices: ['Yes', 'No'],
        branching: {
            type: SurveyQuestionBranchingType.NextQuestion,
        },
    }
    const after: MultipleSurveyQuestion = {
        ...before,
        branching: {
            type: SurveyQuestionBranchingType.End,
        },
    }

    test('describes branching changes', () => {
        const changes = describeBranchingChanges(before, after)
        expect(changes).toHaveLength(1)
        expect(getTextContent(changes[0])).toBe('updated branching logic')
    })
})

describe('describeQuestionChanges', () => {
    const before: MultipleSurveyQuestion = {
        question: 'Do you like ice cream?',
        type: SurveyQuestionType.SingleChoice,
        description: 'Please answer honestly',
        optional: false,
        buttonText: 'Next',
        choices: ['Yes', 'No'],
        branching: {
            type: SurveyQuestionBranchingType.NextQuestion,
        },
    }
    const after: MultipleSurveyQuestion = {
        question: 'Do you like pizza?',
        type: SurveyQuestionType.MultipleChoice,
        description: 'Please answer honestly',
        optional: true,
        buttonText: 'Continue',
        choices: ['Yes', 'No', 'Maybe'],
        branching: {
            type: SurveyQuestionBranchingType.End,
        },
    }
    test('describes all changes in a question', () => {
        const changes = describeQuestionChanges(before, after)
        expect(changes).toHaveLength(6)
        expect(getTextContent(changes[0])).toBe(
            'changed question text from "Do you like ice cream?" to "Do you like pizza?"'
        )
        expect(getTextContent(changes[1])).toBe('made question optional')
        expect(getTextContent(changes[2])).toBe('changed button text from "Next" to "Continue"')
        expect(getTextContent(changes[3])).toBe(
            'changed question type from Single choice select to Multiple choice select'
        )
        expect(getTextContent(changes[4])).toBe('added choices: Maybe')
        expect(getTextContent(changes[5])).toBe('updated branching logic')
    })
})

import { JSONContent } from '@tiptap/core'

import { SurveyQuestionType } from '~/types'

import { FormQuestionType } from '../../formTypes'
import { extractNameFromContent } from '../../surveyFormBuilderLogic'
import { toSurveyQuestions } from './formQuestionAdapter'

function questionNode(questionId: string, questionData: Record<string, unknown>): JSONContent {
    return {
        type: 'formQuestion',
        attrs: { questionId, questionData: JSON.stringify(questionData) },
    }
}

function doc(...children: JSONContent[]): JSONContent {
    return { type: 'doc', content: children }
}

describe('formQuestionAdapter', () => {
    describe('toSurveyQuestions', () => {
        it.each([
            {
                name: 'ShortText → Open',
                questionData: { type: FormQuestionType.ShortText, question: 'Name?', optional: false, id: 'q1' },
                expected: { type: SurveyQuestionType.Open, question: 'Name?', optional: false, id: 'q1' },
            },
            {
                name: 'LongText → Open',
                questionData: { type: FormQuestionType.LongText, question: 'Details?', optional: true, id: 'q2' },
                expected: { type: SurveyQuestionType.Open, question: 'Details?', optional: true, id: 'q2' },
            },
            {
                name: 'SingleChoice → SingleChoice with choices',
                questionData: {
                    type: FormQuestionType.SingleChoice,
                    question: 'Pick one',
                    optional: false,
                    id: 'q3',
                    choices: ['A', 'B'],
                    hasOpenChoice: true,
                },
                expected: {
                    type: SurveyQuestionType.SingleChoice,
                    question: 'Pick one',
                    optional: false,
                    id: 'q3',
                    choices: ['A', 'B'],
                    hasOpenChoice: true,
                },
            },
            {
                name: 'MultipleChoice → MultipleChoice',
                questionData: {
                    type: FormQuestionType.MultipleChoice,
                    question: 'Pick many',
                    optional: false,
                    id: 'q4',
                    choices: ['X', 'Y', 'Z'],
                    hasOpenChoice: false,
                },
                expected: {
                    type: SurveyQuestionType.MultipleChoice,
                    question: 'Pick many',
                    optional: false,
                    id: 'q4',
                    choices: ['X', 'Y', 'Z'],
                    hasOpenChoice: false,
                },
            },
            {
                name: 'NumberRating → Rating with number display',
                questionData: {
                    type: FormQuestionType.NumberRating,
                    question: 'Rate us',
                    optional: false,
                    id: 'q5',
                    scale: 10,
                    lowerBoundLabel: 'Bad',
                    upperBoundLabel: 'Great',
                    isNpsQuestion: true,
                },
                expected: {
                    type: SurveyQuestionType.Rating,
                    question: 'Rate us',
                    optional: false,
                    id: 'q5',
                    display: 'number',
                    scale: 10,
                    lowerBoundLabel: 'Bad',
                    upperBoundLabel: 'Great',
                    isNpsQuestion: true,
                },
            },
            {
                name: 'StarRating → Rating with emoji display',
                questionData: {
                    type: FormQuestionType.StarRating,
                    question: 'Stars?',
                    optional: false,
                    id: 'q6',
                    scale: 5,
                },
                expected: {
                    type: SurveyQuestionType.Rating,
                    question: 'Stars?',
                    optional: false,
                    id: 'q6',
                    display: 'emoji',
                    scale: 5,
                    lowerBoundLabel: '',
                    upperBoundLabel: '',
                },
            },
        ])('$name', ({ questionData, expected }) => {
            const content = doc(
                { type: 'heading', content: [{ type: 'text', text: 'Title' }] },
                questionNode(questionData.id as string, questionData)
            )
            const result = toSurveyQuestions(content)
            expect(result).toEqual([expected])
        })

        it('extracts multiple questions in document order', () => {
            const content = doc(
                { type: 'heading', content: [{ type: 'text', text: 'Title' }] },
                questionNode('q1', {
                    type: FormQuestionType.ShortText,
                    question: 'First',
                    optional: false,
                    id: 'q1',
                }),
                { type: 'paragraph', content: [{ type: 'text', text: 'Some text' }] },
                questionNode('q2', {
                    type: FormQuestionType.LongText,
                    question: 'Second',
                    optional: true,
                    id: 'q2',
                })
            )
            const result = toSurveyQuestions(content)
            expect(result).toHaveLength(2)
            expect(result[0].question).toBe('First')
            expect(result[1].question).toBe('Second')
        })

        it('returns empty array for document with no questions', () => {
            const content = doc({ type: 'heading', content: [{ type: 'text', text: 'Title' }] }, { type: 'paragraph' })
            expect(toSurveyQuestions(content)).toEqual([])
        })

        it('overrides question id with node questionId attr', () => {
            const content = doc(
                questionNode('override-id', {
                    type: FormQuestionType.ShortText,
                    question: 'Q',
                    optional: false,
                    id: 'original-id',
                })
            )
            const result = toSurveyQuestions(content)
            expect(result[0].id).toBe('override-id')
        })

        it('handles questionData as object (not string)', () => {
            const content = doc({
                type: 'formQuestion',
                attrs: {
                    questionId: 'q1',
                    questionData: {
                        type: FormQuestionType.ShortText,
                        question: 'Object data',
                        optional: false,
                        id: 'q1',
                    },
                },
            })
            const result = toSurveyQuestions(content)
            expect(result[0].question).toBe('Object data')
        })
    })
})

describe('extractNameFromContent', () => {
    it.each([
        {
            name: 'extracts text from first heading',
            content: doc({ type: 'heading', content: [{ type: 'text', text: 'My Form' }] }),
            expected: 'My Form',
        },
        {
            name: 'trims whitespace',
            content: doc({ type: 'heading', content: [{ type: 'text', text: '  Spaced  ' }] }),
            expected: 'Spaced',
        },
        {
            name: 'joins multiple text nodes in heading',
            content: doc({
                type: 'heading',
                content: [
                    { type: 'text', text: 'Hello ' },
                    { type: 'text', text: 'World' },
                ],
            }),
            expected: 'Hello World',
        },
        {
            name: 'returns default for empty heading',
            content: doc({ type: 'heading', content: [] }),
            expected: 'Untitled form',
        },
        {
            name: 'returns default for whitespace-only heading',
            content: doc({ type: 'heading', content: [{ type: 'text', text: '   ' }] }),
            expected: 'Untitled form',
        },
        {
            name: 'returns default for doc with no heading',
            content: doc({ type: 'paragraph', content: [{ type: 'text', text: 'Not a heading' }] }),
            expected: 'Untitled form',
        },
        {
            name: 'returns default for empty doc',
            content: { type: 'doc' },
            expected: 'Untitled form',
        },
    ])('$name', ({ content, expected }) => {
        expect(extractNameFromContent(content)).toBe(expected)
    })
})

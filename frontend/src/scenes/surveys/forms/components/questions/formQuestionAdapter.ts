import { JSONContent } from '@tiptap/core'

import { SurveyRatingScaleValue } from 'scenes/surveys/constants'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { FormQuestion, FormQuestionType } from '../../formTypes'

function toSurveyQuestion(fq: FormQuestion): SurveyQuestion {
    const base = { id: fq.id, question: fq.question, optional: fq.optional }
    switch (fq.type) {
        case FormQuestionType.ShortText:
        case FormQuestionType.LongText:
            return { ...base, type: SurveyQuestionType.Open }
        case FormQuestionType.SingleChoice:
            return {
                ...base,
                type: SurveyQuestionType.SingleChoice,
                choices: fq.choices,
                hasOpenChoice: fq.hasOpenChoice,
            }
        case FormQuestionType.MultipleChoice:
            return {
                ...base,
                type: SurveyQuestionType.MultipleChoice,
                choices: fq.choices,
                hasOpenChoice: fq.hasOpenChoice,
            }
        case FormQuestionType.NumberRating:
            return {
                ...base,
                type: SurveyQuestionType.Rating,
                display: 'number',
                scale: fq.scale as SurveyRatingScaleValue,
                lowerBoundLabel: fq.lowerBoundLabel,
                upperBoundLabel: fq.upperBoundLabel,
                isNpsQuestion: fq.isNpsQuestion,
            }
        case FormQuestionType.StarRating:
            return {
                ...base,
                type: SurveyQuestionType.Rating,
                display: 'emoji',
                scale: fq.scale as SurveyRatingScaleValue,
                lowerBoundLabel: '',
                upperBoundLabel: '',
            }
    }
}

export function toSurveyQuestions(content: JSONContent): SurveyQuestion[] {
    const questions: SurveyQuestion[] = []

    function walk(node: JSONContent): void {
        if (node.type === 'formQuestion' && node.attrs) {
            const data = node.attrs.questionData
            const parsed: FormQuestion = typeof data === 'string' ? JSON.parse(data) : data
            if (node.attrs.questionId) {
                parsed.id = node.attrs.questionId
            }
            questions.push(toSurveyQuestion(parsed))
        }
        if (node.content) {
            for (const child of node.content) {
                walk(child)
            }
        }
    }

    walk(content)
    return questions
}

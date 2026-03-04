import { v4 as uuidv4 } from 'uuid'

import { IconCheckbox, IconMessage, IconStar, IconToggle } from '@posthog/icons'

import { Icon123 } from 'lib/lemon-ui/icons'

import {
    FormStarRatingQuestion,
    FormNumberScaleQuestion,
    FormQuestion,
    FormQuestionType,
    QuestionTypeSetting,
    SettingType,
} from '../../formTypes'
import { ChoicePreview } from './previews/ChoicePreview'
import { LongTextPreview } from './previews/LongTextPreview'
import { RatingPreview } from './previews/RatingPreview'
import { ShortTextPreview } from './previews/ShortTextPreview'

export interface QuestionPreviewProps {
    question: FormQuestion
    onUpdate: (q: FormQuestion) => void
}

interface QuestionTypeEntry {
    label: string
    icon: JSX.Element
    keywords: string[]
    slashDescription: string
    defaultQuestion: (id: string) => FormQuestion
    Preview: (props: QuestionPreviewProps) => JSX.Element
    settings?: (question: FormQuestion) => QuestionTypeSetting[]
}

export const QUESTION_TYPE_REGISTRY: Record<FormQuestionType, QuestionTypeEntry> = {
    [FormQuestionType.ShortText]: {
        label: 'Short answer',
        icon: <IconMessage />,
        keywords: ['text', 'input', 'open', 'short', 'answer'],
        slashDescription: 'Single line text input',
        defaultQuestion: (id) => ({
            type: FormQuestionType.ShortText,
            question: 'Your question here',
            optional: false,
            id,
        }),
        Preview: ShortTextPreview,
    },
    [FormQuestionType.LongText]: {
        label: 'Long answer',
        icon: <IconMessage />,
        keywords: ['text', 'textarea', 'long', 'paragraph', 'answer'],
        slashDescription: 'Multi-line text input',
        defaultQuestion: (id) => ({
            type: FormQuestionType.LongText,
            question: 'Your question here',
            optional: false,
            id,
        }),
        Preview: LongTextPreview,
    },
    [FormQuestionType.SingleChoice]: {
        label: 'Single choice',
        icon: <IconToggle />,
        keywords: ['radio', 'single', 'choice', 'select', 'one'],
        slashDescription: 'Select one option from a list',
        defaultQuestion: (id) => ({
            type: FormQuestionType.SingleChoice,
            question: 'Your question here',
            choices: ['Option 1', 'Option 2'],
            hasOpenChoice: false,
            optional: false,
            id,
        }),
        Preview: ChoicePreview,
    },
    [FormQuestionType.MultipleChoice]: {
        label: 'Multiple choice',
        icon: <IconCheckbox />,
        keywords: ['checkbox', 'multiple', 'choice', 'multi', 'select'],
        slashDescription: 'Select multiple options',
        defaultQuestion: (id) => ({
            type: FormQuestionType.MultipleChoice,
            question: 'Your question here',
            choices: ['Option 1', 'Option 2', 'Option 3'],
            hasOpenChoice: false,
            optional: false,
            id,
        }),
        Preview: ChoicePreview,
    },
    [FormQuestionType.NumberRating]: {
        label: 'Number scale',
        icon: <Icon123 />,
        keywords: ['rating', 'scale', 'nps', 'score', 'number'],
        slashDescription: 'Number scale rating',
        defaultQuestion: (id) => ({
            type: FormQuestionType.NumberRating,
            question: 'How would you rate this?',
            scale: 5,
            lowerBoundLabel: 'Very unlikely',
            upperBoundLabel: 'Very likely',
            isNpsQuestion: false,
            optional: false,
            id,
        }),
        Preview: RatingPreview,
        settings: (question) => {
            const q = question as FormNumberScaleQuestion
            const options: QuestionTypeSetting[] = [
                {
                    type: SettingType.Select,
                    label: 'Scale',
                    value: q.scale,
                    apply: (v: string | number) => {
                        const newScale = parseInt(v.toString())
                        const newQuestion: FormNumberScaleQuestion = {
                            ...q,
                            scale: newScale,
                            isNpsQuestion: newScale === 10,
                        }
                        return newQuestion
                    },
                    options: [
                        { label: '1-5', value: 5 },
                        { label: '1-7', value: 7 },
                        { label: '1-10', value: 10 },
                    ],
                },
            ]
            if (q.scale === 10) {
                options.push({
                    type: SettingType.Toggle,
                    label: 'NPS Question',
                    checked: q.isNpsQuestion,
                    apply: (v: boolean) => ({ ...q, isNpsQuestion: v }) as FormQuestion,
                })
            }
            return options
        },
    },
    [FormQuestionType.StarRating]: {
        label: 'Star rating',
        icon: <IconStar />,
        keywords: ['rating', 'star', 'stars', 'score'],
        slashDescription: 'Star scale rating',
        defaultQuestion: (id) => ({
            type: FormQuestionType.StarRating,
            question: 'How would you rate this?',
            scale: 5,
            optional: false,
            id,
        }),
        Preview: RatingPreview,
        settings: (question) => {
            const q = question as FormStarRatingQuestion
            return [
                {
                    type: SettingType.Select,
                    label: 'Stars',
                    value: q.scale,
                    apply: (v: string | number) => ({ ...q, scale: parseInt(v.toString()) }) as FormQuestion,
                    options: [
                        { label: '1-3', value: 3 },
                        { label: '1-5', value: 5 },
                    ],
                },
            ]
        },
    },
}

export function getDefaultQuestion(type: FormQuestionType): { questionId: string; question: FormQuestion } {
    const questionId = uuidv4()
    return { questionId, question: QUESTION_TYPE_REGISTRY[type].defaultQuestion(questionId) }
}

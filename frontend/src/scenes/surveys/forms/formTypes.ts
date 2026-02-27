import { JSONContent } from '@tiptap/core'

export enum FormQuestionType {
    ShortText = 'short_text',
    LongText = 'long_text',
    SingleChoice = 'single_choice',
    MultipleChoice = 'multiple_choice',
    NumberRating = 'number_rating',
    StarRating = 'star_rating',
}

export interface FormQuestionBase {
    id: string
    question: string
    optional: boolean
}

export interface FormShortTextQuestion extends FormQuestionBase {
    type: FormQuestionType.ShortText
}

export interface FormLongTextQuestion extends FormQuestionBase {
    type: FormQuestionType.LongText
}

export interface FormSingleChoiceQuestion extends FormQuestionBase {
    type: FormQuestionType.SingleChoice
    choices: string[]
    hasOpenChoice: boolean
}

export interface FormMultipleChoiceQuestion extends FormQuestionBase {
    type: FormQuestionType.MultipleChoice
    choices: string[]
    hasOpenChoice: boolean
}

interface FormRatingBase extends FormQuestionBase {
    scale: number
}

export interface FormNumberScaleQuestion extends FormRatingBase {
    type: FormQuestionType.NumberRating
    lowerBoundLabel: string
    upperBoundLabel: string
    isNpsQuestion: boolean
}

export interface FormStarRatingQuestion extends FormRatingBase {
    type: FormQuestionType.StarRating
}

export type FormChoiceQuestion = FormSingleChoiceQuestion | FormMultipleChoiceQuestion

export type FormQuestion =
    | FormShortTextQuestion
    | FormLongTextQuestion
    | FormChoiceQuestion
    | FormNumberScaleQuestion
    | FormStarRatingQuestion

export enum SettingType {
    Select = 'select',
    Toggle = 'toggle',
    Input = 'input',
}

export interface SelectSetting {
    type: SettingType.Select
    label: string
    value: string | number
    apply: (value: string | number) => FormQuestion
    options: { label: string; value: string | number }[]
}

export interface ToggleSetting {
    type: SettingType.Toggle
    label: string
    checked: boolean
    apply: (checked: boolean) => FormQuestion
    children?: QuestionTypeSetting[]
}

export interface InputSetting {
    type: SettingType.Input
    label: string
    value: string | number
    placeholder?: string
    inputType?: 'text' | 'number'
    apply: (value: string | number) => FormQuestion
}

export type QuestionTypeSetting = SelectSetting | ToggleSetting | InputSetting

export interface FormContentStorage {
    content: JSONContent | null
    showLogo: boolean
    showCover: boolean
    coverColor: string
    logoUrl: string | null
    logoMediaId: string | null
    coverImageUrl: string | null
    coverImageMediaId: string | null
    coverImagePosition: { x: number; y: number }
}

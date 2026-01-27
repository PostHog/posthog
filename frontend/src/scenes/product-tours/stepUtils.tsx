import { JSONContent } from '@tiptap/core'

import { IconCursorClick, IconMessage, IconQuestion } from '@posthog/icons'

import { uuid } from 'lib/utils'

import {
    ProductTourStep,
    ProductTourStepType,
    ProductTourSurveyQuestion,
    ProductTourSurveyQuestionType,
    SurveyPosition,
} from '~/types'

export const DEFAULT_RATING_QUESTION = 'How helpful was this tour?'
export const DEFAULT_OPEN_QUESTION = 'Any feedback on this tour?'

// these are partials because 'banner' is a valid step type, but NOT used in the toolbar builder
export const STEP_TYPE_ICONS: Partial<Record<ProductTourStepType, JSX.Element>> = {
    element: <IconCursorClick className="w-3.5 h-3.5" />,
    modal: <IconMessage className="w-3.5 h-3.5" />,
    survey: <IconQuestion className="w-3.5 h-3.5" />,
}
export const STEP_TYPE_LABELS: Partial<Record<ProductTourStepType, string>> = {
    element: 'Element',
    modal: 'Pop-up',
    survey: 'Survey',
}

export function getDefaultStepContent(): JSONContent {
    return {
        type: 'doc',
        content: [
            {
                type: 'paragraph',
            },
        ],
    }
}

export function getDefaultSurveyContent(type: ProductTourSurveyQuestionType): ProductTourSurveyQuestion {
    if (type === 'rating') {
        return {
            type: 'rating',
            questionText: DEFAULT_RATING_QUESTION,
            display: 'emoji',
            scale: 5,
            lowerBoundLabel: 'Not at all',
            upperBoundLabel: 'Very much',
        }
    }
    return {
        type: 'open',
        questionText: DEFAULT_OPEN_QUESTION,
    }
}

export function getStepTitle(step: ProductTourStep, index: number): string {
    if (step.type === 'survey' && step.survey?.questionText) {
        const text = step.survey.questionText
        return text.length > 30 ? text.slice(0, 30) + '...' : text
    }

    if (step.content && typeof step.content === 'object') {
        const doc = step.content as { content?: Array<{ content?: Array<{ text?: string }> }> }
        const firstContent = doc.content?.[0]
        if (firstContent?.content?.[0]?.text) {
            const text = firstContent.content[0].text
            return text.length > 30 ? text.slice(0, 30) + '...' : text
        }
    }

    const typeLabel = STEP_TYPE_LABELS[step.type] ?? step.type
    return `${typeLabel} step ${index + 1}`
}

export function createDefaultStep(type: ProductTourStepType): ProductTourStep {
    const baseStep: ProductTourStep = {
        id: uuid(),
        type,
        content: type === 'modal' ? getDefaultStepContent() : null,
        progressionTrigger: 'button',
        modalPosition: SurveyPosition.MiddleCenter,
    }

    if (type === 'survey') {
        return { ...baseStep, survey: getDefaultSurveyContent('rating') }
    }

    return baseStep
}

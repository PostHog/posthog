import { JSONContent } from '@tiptap/core'

import { IconMessage, IconQuestion } from '@posthog/icons'

import { uuid } from 'lib/utils'

import {
    PRODUCT_TOUR_STEP_WIDTHS,
    ProductTourStep,
    ProductTourStepType,
    ProductTourStepWidth,
    ProductTourSurveyQuestion,
    ProductTourSurveyQuestionType,
    SurveyPosition,
} from '~/types'

export const DEFAULT_RATING_QUESTION = 'How helpful was this tour?'
export const DEFAULT_OPEN_QUESTION = 'Any feedback on this tour?'

export function getStepIcon(type: ProductTourStepType): JSX.Element {
    if (type === 'survey') {
        return <IconQuestion className="w-3.5 h-3.5" />
    }
    return <IconMessage className="w-3.5 h-3.5" />
}

export function getStepLabel(type: ProductTourStepType): string {
    if (type === 'survey') {
        return 'Survey'
    }
    return 'Pop-up'
}

export function getDefaultStepContent(): JSONContent {
    return {
        type: 'doc',
        content: [
            {
                type: 'heading',
                attrs: { level: 1 },
                content: [{ type: 'text', text: 'Step title' }],
            },
            {
                type: 'paragraph',
                content: [{ type: 'text', text: 'Describe what this element does...' }],
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

    const typeLabel = getStepLabel(step.type)
    return `${typeLabel} step ${index + 1}`
}

export function getWidthValue(maxWidth: ProductTourStep['maxWidth']): number {
    if (typeof maxWidth === 'number') {
        return maxWidth
    }
    if (maxWidth && maxWidth in PRODUCT_TOUR_STEP_WIDTHS) {
        return PRODUCT_TOUR_STEP_WIDTHS[maxWidth as ProductTourStepWidth]
    }
    return PRODUCT_TOUR_STEP_WIDTHS.default
}

export function hasElementTarget(step: ProductTourStep): boolean {
    if (step.useManualSelector) {
        return !!step.selector
    }
    return !!step.inferenceData
}

export function hasIncompleteTargeting(step: ProductTourStep): boolean {
    const needsTarget = step.type === 'element' || !!step.useManualSelector
    return needsTarget && !hasElementTarget(step)
}

export function createDefaultStep(type: ProductTourStepType): ProductTourStep {
    const baseStep: ProductTourStep = {
        id: uuid(),
        type,
        content: type === 'survey' ? null : getDefaultStepContent(),
        progressionTrigger: 'button',
        modalPosition: SurveyPosition.MiddleCenter,
    }

    if (type === 'survey') {
        return { ...baseStep, survey: getDefaultSurveyContent('rating') }
    }

    return baseStep
}

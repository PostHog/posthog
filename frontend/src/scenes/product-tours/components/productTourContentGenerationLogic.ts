import { JSONContent } from '@tiptap/core'
import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'

import { ProductTourGeneratedStepContent } from '~/types'

import { productTourLogic } from '../productTourLogic'
import type { productTourContentGenerationLogicType } from './productTourContentGenerationLogicType'

export interface ProductTourContentGenerationLogicProps {
    tourId: string
}

export interface ContentSuggestion {
    stepId: string
    title: string
    description: string
    tiptap: JSONContent
    status: 'pending' | 'applied' | 'dismissed'
}

function buildTiptapDoc(title: string, description: string): JSONContent {
    return {
        type: 'doc',
        content: [
            { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: title }] },
            { type: 'paragraph', content: [{ type: 'text', text: description }] },
        ],
    }
}

export const productTourContentGenerationLogic = kea<productTourContentGenerationLogicType>([
    path(['scenes', 'product-tours', 'components', 'productTourContentGenerationLogic']),
    props({} as ProductTourContentGenerationLogicProps),
    key((props) => props.tourId),

    actions({
        openModal: true,
        closeModal: true,
        setGoal: (goal: string) => ({ goal }),
        generateContent: true,
        setGenerating: (generating: boolean) => ({ generating }),
        setError: (error: string | null) => ({ error }),
        setSuggestions: (suggestions: ContentSuggestion[]) => ({ suggestions }),
        applySuggestion: (stepId: string) => ({ stepId }),
        dismissSuggestion: (stepId: string) => ({ stepId }),
        applyAllSuggestions: true,
        reset: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                reset: () => false,
            },
        ],
        goal: [
            '',
            {
                setGoal: (_, { goal }) => goal,
                closeModal: () => '',
                reset: () => '',
            },
        ],
        isGenerating: [
            false,
            {
                setGenerating: (_, { generating }) => generating,
                reset: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
                generateContent: () => null,
                closeModal: () => null,
                reset: () => null,
            },
        ],
        suggestions: [
            [] as ContentSuggestion[],
            {
                setSuggestions: (_, { suggestions }) => suggestions,
                dismissSuggestion: (state, { stepId }) =>
                    state.map((s) =>
                        s.stepId === stepId && s.status === 'pending' ? { ...s, status: 'dismissed' as const } : s
                    ),
                reset: () => [],
            },
        ],
    }),

    selectors({
        pendingSuggestions: [
            (s) => [s.suggestions],
            (suggestions): ContentSuggestion[] => suggestions.filter((s) => s.status === 'pending'),
        ],
        hasPendingSuggestions: [(s) => [s.pendingSuggestions], (pending): boolean => pending.length > 0],
    }),

    listeners(({ actions, values, props }) => ({
        generateContent: async () => {
            const logic = productTourLogic({ id: props.tourId })
            const form = logic.values.productTourForm
            const steps = form.content?.steps ?? []

            if (steps.length === 0) {
                actions.setError('Add at least one step before generating content.')
                return
            }

            actions.setGenerating(true)

            try {
                const response = await api.productTours.generateContent(props.tourId, form.name, steps, values.goal)

                const suggestions: ContentSuggestion[] = response.steps.map(
                    (generated: ProductTourGeneratedStepContent) => ({
                        stepId: generated.step_id,
                        title: generated.title,
                        description: generated.description,
                        tiptap: buildTiptapDoc(generated.title, generated.description),
                        status: 'pending' as const,
                    })
                )

                actions.setSuggestions(suggestions)
                actions.closeModal()
            } catch {
                actions.setError('Failed to generate content. Please try again.')
            }

            actions.setGenerating(false)
        },

        applySuggestion: ({ stepId }) => {
            const suggestion = values.suggestions.find((s) => s.stepId === stepId && s.status === 'pending')
            if (!suggestion) {
                return
            }

            const logic = productTourLogic({ id: props.tourId })
            const steps = logic.values.productTourForm.content?.steps ?? []
            const stepIndex = steps.findIndex((s) => s.id === stepId)
            if (stepIndex >= 0) {
                logic.actions.setSelectedStepIndex(stepIndex)
                logic.actions.updateSelectedStep({ content: suggestion.tiptap })
            }

            actions.setSuggestions(
                values.suggestions.map((s) =>
                    s.stepId === stepId && s.status === 'pending' ? { ...s, status: 'applied' as const } : s
                )
            )
        },

        applyAllSuggestions: () => {
            const logic = productTourLogic({ id: props.tourId })
            const form = logic.values.productTourForm
            const steps = [...(form.content?.steps ?? [])]

            for (const suggestion of values.suggestions) {
                if (suggestion.status === 'pending') {
                    const stepIndex = steps.findIndex((s) => s.id === suggestion.stepId)
                    if (stepIndex >= 0) {
                        steps[stepIndex] = { ...steps[stepIndex], content: suggestion.tiptap }
                    }
                }
            }

            logic.actions.setProductTourFormValue('content', {
                ...form.content,
                steps,
            })

            actions.setSuggestions(
                values.suggestions.map((s) => (s.status === 'pending' ? { ...s, status: 'applied' as const } : s))
            )
        },
    })),
])

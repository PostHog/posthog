import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { productTourLogic } from '../productTourLogic'
import { productTourContentGenerationLogic } from './productTourContentGenerationLogic'

export interface StepContentSuggestionProps {
    tourId: string
}

export function StepContentSuggestion({ tourId }: StepContentSuggestionProps): JSX.Element | null {
    const { productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))
    const { suggestions, pendingSuggestions } = useValues(productTourContentGenerationLogic({ tourId }))
    const { applySuggestion, dismissSuggestion, applyAllSuggestions } = useActions(
        productTourContentGenerationLogic({ tourId })
    )

    const selectedStep = productTourForm.content?.steps?.[selectedStepIndex]
    const suggestion = selectedStep
        ? suggestions.find((s) => s.stepId === selectedStep.id && s.status === 'pending')
        : undefined

    if (!suggestion || !selectedStep) {
        return null
    }

    return (
        <LemonBanner type="ai" onClose={() => dismissSuggestion(selectedStep.id)}>
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-sm">{suggestion.title}</span>
                    <span className="text-xs text-muted">{suggestion.description}</span>
                </div>

                <div className="flex items-center justify-between">
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconCheck />}
                            onClick={() => applySuggestion(selectedStep.id)}
                        >
                            Apply
                        </LemonButton>
                        <LemonButton type="tertiary" size="small" onClick={applyAllSuggestions}>
                            Apply all ({pendingSuggestions.length})
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}

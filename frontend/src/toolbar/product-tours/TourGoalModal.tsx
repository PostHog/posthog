import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { productToursLogic } from './productToursLogic'

const GOAL_SUGGESTIONS = [
    'Quick overview of the page',
    'Introduce key features',
    'Onboard new users',
    'Explain a workflow',
    'Highlight new changes',
]

export function TourGoalModal(): JSX.Element | null {
    const { theme } = useValues(toolbarLogic)
    const { goalModalOpen, aiGoal } = useValues(productToursLogic)
    const { closeGoalModal, setAIGoal, startFromGoalModal } = useActions(productToursLogic)

    const canProceed = aiGoal.trim().length > 0

    return (
        <LemonModal
            isOpen={goalModalOpen}
            onClose={closeGoalModal}
            title="Create a product tour"
            description="Tell us what you want users to learn from this tour."
            footer={
                <div className="flex justify-end gap-2 w-full">
                    <LemonButton type="secondary" onClick={closeGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={startFromGoalModal}
                        disabledReason={!canProceed ? 'Enter a goal first' : undefined}
                    >
                        Start building
                    </LemonButton>
                </div>
            }
            {...({ theme } as { theme?: string })}
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium mb-2 block">What should users learn?</label>
                    <LemonInput
                        placeholder="e.g., How to create their first dashboard"
                        value={aiGoal}
                        onChange={setAIGoal}
                        autoFocus
                    />
                </div>

                <div>
                    <label className="text-xs text-muted mb-2 block">Or pick a suggestion:</label>
                    <div className="flex flex-wrap gap-2">
                        {GOAL_SUGGESTIONS.map((suggestion) => (
                            <LemonButton
                                key={suggestion}
                                size="xsmall"
                                type={aiGoal === suggestion ? 'primary' : 'secondary'}
                                onClick={() => setAIGoal(suggestion)}
                            >
                                {suggestion}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

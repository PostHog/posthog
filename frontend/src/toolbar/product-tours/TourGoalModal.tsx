import { useActions, useValues } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

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
    const { goalModalOpen, aiGoal, useAIGeneration } = useValues(productToursLogic)
    const { closeGoalModal, setAIGoal, setUseAIGeneration, startSelectionMode } = useActions(productToursLogic)

    if (!goalModalOpen) {
        return null
    }

    const canProceed = aiGoal.trim().length > 0

    return (
        <LemonModal
            isOpen={goalModalOpen}
            onClose={closeGoalModal}
            title="Create a product tour"
            description="First, tell us what you want users to learn from this tour."
            footer={
                <div className="flex justify-end gap-2 w-full">
                    <LemonButton type="secondary" onClick={closeGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={startSelectionMode}
                        disabledReason={!canProceed ? 'Enter a goal first' : undefined}
                    >
                        Start selecting elements
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

                <div className="border-t pt-4">
                    <LemonCheckbox
                        checked={useAIGeneration}
                        onChange={setUseAIGeneration}
                        label={
                            <span className="flex items-center gap-1.5">
                                <IconMagicWand className="w-4 h-4" />
                                Generate content with AI
                            </span>
                        }
                    />
                    <p className="text-xs text-muted mt-1 ml-6">
                        AI will write titles and descriptions for each step based on your goal
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}

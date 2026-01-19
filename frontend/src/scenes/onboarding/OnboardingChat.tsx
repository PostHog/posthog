import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect } from 'react'
import { onboardingChatLogic } from './onboardingChatLogic'
import { Thread } from 'scenes/max/Thread'
import { QuestionInput } from 'scenes/max/components/QuestionInput'
import { maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { OnboardingStepKey } from '~/types'

export function OnboardingChat(): JSX.Element {
    const { currentStep, productKey, allSteps, currentStepIndex } = useValues(onboardingChatLogic)
    const { initializeOnboarding, completeCurrentStep, skipCurrentStep } = useActions(onboardingChatLogic)
    const { conversation, messages } = useValues(maxThreadLogic({ conversation_id: 'onboarding' }))

    useEffect(() => {
        if (productKey) {
            initializeOnboarding(productKey)
        }
    }, [productKey])

    return (
        <div className="flex flex-col h-full">
            {/* Progress indicator */}
            <div className="border-b p-4">
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-xl font-semibold">Getting started with PostHog</h2>
                    <span className="text-sm text-muted">
                        Step {currentStepIndex + 1} of {allSteps.length}
                    </span>
                </div>
                <div className="w-full bg-border rounded-full h-2">
                    <div
                        className="bg-primary h-2 rounded-full transition-all"
                        style={{ width: `${((currentStepIndex + 1) / allSteps.length) * 100}%` }}
                    />
                </div>
            </div>

            {/* Chat interface */}
            <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-1 overflow-y-auto">
                    <Thread conversation={conversation} messages={messages} />
                </div>

                {/* Input area */}
                <div className="border-t p-4">
                    <QuestionInput conversationId="onboarding" />

                    {/* Quick action buttons */}
                    <div className="flex gap-2 mt-2">
                        {currentStep && (
                            <>
                                <LemonButton type="secondary" size="small" onClick={skipCurrentStep}>
                                    Skip this step
                                </LemonButton>
                            </>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

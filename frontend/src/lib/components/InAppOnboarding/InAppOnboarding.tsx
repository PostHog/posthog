import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

import { inAppOnboardingLogic } from './inAppOnboardingLogic'

/** The card for the in-app onboarding flow the user is on. Each step asks for something to do in the app,
 * and moves on once they have done it. */
export function InAppOnboarding(): JSX.Element | null {
    const { activeFlow, activeProgress, isActiveFlowComplete } = useValues(inAppOnboardingLogic)
    const { skipFlow, closeFlow, reportFlowShown } = useActions(inAppOnboardingLogic)

    const activeFlowKey = activeFlow?.key
    useEffect(() => {
        if (activeFlowKey) {
            reportFlowShown(activeFlowKey)
        }
    }, [activeFlowKey, reportFlowShown])

    if (!activeFlow) {
        return null
    }

    const step = isActiveFlowComplete ? activeFlow.completion : activeFlow.steps[activeProgress.stepIndex]
    const times = isActiveFlowComplete ? 1 : activeFlow.steps[activeProgress.stepIndex].times

    return (
        <LemonCard
            hoverEffect={false}
            className="fixed bottom-4 left-1/2 -translate-x-1/2 w-80 max-w-[calc(100vw-2rem)] p-4 shadow-lg z-[var(--z-bottom-notice)]"
            data-attr={`in-app-onboarding-${activeFlow.key}`}
        >
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <span className="font-semibold">{activeFlow.title}</span>
                    {!isActiveFlowComplete && (
                        <span translate="no">
                            {activeProgress.stepIndex + 1} of {activeFlow.steps.length}
                        </span>
                    )}
                </div>
                {step.keys && (
                    <KeyboardShortcut
                        // Re-keyed per step so the shortcut swaps cleanly when the step changes.
                        key={`${activeProgress.stepIndex}-${step.keys.join('+')}`}
                        {...Object.fromEntries(step.keys.map((key) => [key, true]))}
                        className="self-start"
                    />
                )}
                <div className="flex flex-col gap-1">
                    <h4 className="m-0 font-semibold">{step.title}</h4>
                    <p className="m-0 text-secondary">{step.description}</p>
                </div>
                {times > 1 && (
                    <div className="flex gap-1" aria-label={`${activeProgress.count} of ${times} done`}>
                        {Array.from({ length: times }, (_, index) => (
                            <span
                                key={index}
                                className={cn(
                                    'h-1.5 flex-1 rounded-full transition-colors motion-reduce:transition-none',
                                    index < activeProgress.count ? 'bg-accent' : 'bg-fill-highlight-100'
                                )}
                            />
                        ))}
                    </div>
                )}
                {isActiveFlowComplete ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        className="self-end"
                        onClick={() => closeFlow(activeFlow.key)}
                        data-attr={`in-app-onboarding-${activeFlow.key}-done`}
                    >
                        Done
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        className="self-end"
                        onClick={() => skipFlow(activeFlow.key)}
                        data-attr={`in-app-onboarding-${activeFlow.key}-skip`}
                    >
                        Skip
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}

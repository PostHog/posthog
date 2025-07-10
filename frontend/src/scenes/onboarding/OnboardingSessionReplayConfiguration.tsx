import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FilmCameraHog } from 'lib/components/hedgehogs'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { onboardingLogic } from './onboardingLogic'

export function OnboardingSessionReplayConfiguration({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    const { goToNextStep, updateCurrentTeam } = useActions(onboardingLogic)

    const handleNext = (enabled: boolean): void => {
        updateCurrentTeam({
            session_recording_opt_in: enabled,
        })
        goToNextStep()
    }

    return (
        <OnboardingStep title="Record user sessions" stepKey={stepKey} continueOverride={<></>}>
            <div className="mb-4">
                <p className="text-secondary">
                    Session Replay records user sessions to help you understand their actions and uncover opportunities
                    for product improvement.
                </p>
            </div>

            <div className="flex flex-col items-center gap-6 md:flex-row">
                <div className="hidden flex-shrink-0 md:block">
                    <FilmCameraHog className="h-auto w-36" />
                </div>
                <div className="bg-bg-light dark:bg-bg-depth flex-1 rounded-lg border border-gray-200 p-4">
                    <h4 className="mb-2 text-lg font-semibold">Why enable Session Replay?</h4>
                    <ul className="deprecated-space-y-2 text-secondary">
                        <li>
                            <strong>Understand user behavior:</strong> Get a clear view of how people navigate and
                            interact with your product.
                        </li>
                        <li>
                            <strong>Identify UI/UX issues:</strong> Spot friction points and increase your product's
                            usability.
                        </li>
                        <li>
                            <strong>Improve customer support:</strong> Quickly diagnose problems for your customers.
                        </li>
                    </ul>
                </div>
            </div>
            <div className="mt-6 flex w-full justify-end gap-2">
                <LemonButton type="secondary" data-attr="skip-session-replay" onClick={() => handleNext(false)}>
                    No, thanks
                </LemonButton>
                <LemonButton type="primary" data-attr="enable-session-replay" onClick={() => handleNext(true)}>
                    Enable Session Replay
                </LemonButton>
            </div>
        </OnboardingStep>
    )
}

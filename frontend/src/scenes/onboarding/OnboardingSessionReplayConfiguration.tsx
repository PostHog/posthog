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

            <div className="flex flex-col md:flex-row items-center gap-6">
                <div className="hidden md:block flex-shrink-0">
                    <FilmCameraHog className="w-36 h-auto" />
                </div>
                <div className="flex-1 border border-gray-200 rounded-lg bg-bg-light dark:bg-bg-depth p-4">
                    <h4 className="text-lg font-semibold mb-2">Why enable Session Replay?</h4>
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
            <div className="mt-6 w-full flex justify-end gap-2">
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

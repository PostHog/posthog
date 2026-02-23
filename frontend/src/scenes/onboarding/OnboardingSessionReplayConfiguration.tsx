import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FilmCameraHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { OnboardingStepComponentType, onboardingLogic } from './onboardingLogic'

export const OnboardingSessionReplayConfiguration: OnboardingStepComponentType = () => {
    const { goToNextStep, updateCurrentTeam } = useActions(onboardingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const mediaVariant = featureFlags[FEATURE_FLAGS.ONBOARDING_SESSION_REPLAY_MEDIA]

    const handleNext = (enabled: boolean): void => {
        window.posthog?.capture('onboarding session replay toggled', { enabled })
        updateCurrentTeam({ session_recording_opt_in: enabled })
        goToNextStep()
    }

    return (
        <OnboardingStep title="Record user sessions" stepKey={OnboardingStepKey.SESSION_REPLAY} showContinue={false}>
            {mediaVariant === 'screenshot' ? (
                <>
                    <p className="text-secondary mb-4">
                        Session Replay records user sessions so you can watch exactly how people use your product and
                        spot opportunities for improvement.
                    </p>

                    <div className="rounded-lg overflow-hidden border border-border">
                        <img
                            className="w-full"
                            src="https://res.cloudinary.com/dmukukwp6/image/upload/w_1600,c_limit,q_auto,f_auto/screenshot_23_02_05_15_26_pm_2b13578105.jpg"
                            alt="Session Replay demo"
                        />
                    </div>
                </>
            ) : (
                <>
                    <div className="mb-4">
                        <p className="text-secondary">
                            Session Replay records user sessions to help you understand their actions and uncover
                            opportunities for product improvement.
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
                                    <strong>Understand user behavior:</strong> Get a clear view of how people navigate
                                    and interact with your product.
                                </li>
                                <li>
                                    <strong>Identify UI/UX issues:</strong> Spot friction points and increase your
                                    product's usability.
                                </li>
                                <li>
                                    <strong>Improve customer support:</strong> Quickly diagnose problems for your
                                    customers.
                                </li>
                            </ul>
                        </div>
                    </div>
                </>
            )}
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

OnboardingSessionReplayConfiguration.stepKey = OnboardingStepKey.SESSION_REPLAY

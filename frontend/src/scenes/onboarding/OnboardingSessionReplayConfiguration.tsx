import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FilmCameraHog } from 'lib/components/hedgehogs'

import { ProductKey } from '~/types'

import { onboardingLogic, type OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export function OnboardingSessionReplayConfiguration({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    const { allBillingProducts } = useValues(onboardingLogic)

    const sessionReplayProduct = allBillingProducts.find((product) => product.type === ProductKey.SESSION_REPLAY)

    return (
        <OnboardingStep title="Record user sessions" stepKey={stepKey} continueOverride={<></>}>
            <div className="mb-4">
                <p className="text-muted">
                    Session Replay records user sessions to help you understand their actions and uncover opportunities
                    for product improvement.
                </p>
            </div>

            <div className="flex flex-col md:flex-row items-start gap-6">
                <div className="hidden md:block flex-shrink-0">
                    <FilmCameraHog className="w-36 h-auto" />
                </div>
                <div className="flex-1 border border-gray-200 rounded-lg bg-white p-4">
                    <h4 className="text-lg font-semibold mb-2">Why enable Session Replay?</h4>
                    <ul className="list-inside list-disc space-y-2 text-muted">
                        {sessionReplayProduct?.features
                            .filter((feature) => feature.type === 'primary')
                            .map((feature) => (
                                <li key={feature.key}>{feature.description}</li>
                            ))}
                    </ul>
                </div>
            </div>
            <div className="mt-6 w-full flex justify-end gap-2">
                <LemonButton
                    type="secondary"
                    data-attr="skip-session-replay"
                    onClick={() => {
                        // Logic if the user does not want to enable session replay yet
                    }}
                >
                    No, thanks
                </LemonButton>
                <LemonButton
                    type="primary"
                    data-attr="enable-session-replay"
                    onClick={() => {
                        // Add logic to enable session replay
                    }}
                >
                    Enable Session Replay
                </LemonButton>
            </div>
        </OnboardingStep>
    )
}

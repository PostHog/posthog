import { OnboardingStep } from 'scenes/onboarding/legacy/OnboardingStep'

import { OnboardingStepKey } from '~/types'

export const OnboardingSupportStep = (): JSX.Element => {
    return (
        <OnboardingStep
            title="Set up Support"
            subtitle="Support puts messages from your customers in one inbox, where your team can reply to them."
            stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
        >
            <div className="flex flex-col gap-2" data-attr="onboarding-support-step">
                <p className="m-0">
                    We turn on Support when you finish onboarding. After that, connect the channels you want to use in
                    Support settings:
                </p>
                <ul className="list-disc pl-6 m-0">
                    <li>A chat widget on your website or app</li>
                    <li>Email</li>
                    <li>Slack</li>
                    <li>The API, to send messages from your own code</li>
                </ul>
            </div>
        </OnboardingStep>
    )
}

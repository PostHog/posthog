import { useActions } from 'kea'

import { LemonDivider, Link } from '@posthog/lemon-ui'

import { ProfessorHog } from 'lib/components/hedgehogs'
import { TeamBusinessModel, TeamDisplayName, TeamTimezone } from 'scenes/settings/environment/TeamSettings'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { onboardingLogic } from './onboardingLogic'

export const OnboardingProjectData = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { completeOnboarding } = useActions(onboardingLogic)

    return (
        <OnboardingStep
            title="Tell us more about your project"
            stepKey={stepKey}
            showSkip
            continueText="Finish"
            onContinue={completeOnboarding}
        >
            <div className="flex flex-col gap-8">
                <div className="flex flex-col-reverse sm:flex-row gap-2">
                    <div>
                        <p className="text-muted mb-2">
                            You're done! You can <Link onClick={() => completeOnboarding()}>access PostHog</Link> now if
                            you want, but we'd love to learn more about your product to help you get the most out of the
                            product.
                        </p>
                        <p className="text-muted text-sm mb-2">
                            All fields are optional, but sharing a bit more about your project helps us provide better
                            insights and recommendations.
                        </p>
                    </div>

                    <ProfessorHog className="w-25 h-25 -mt-3" />
                </div>

                <LemonDivider />

                <div className="flex flex-col">
                    <h3 className="font-semibold mb-2">Project name</h3>
                    <TeamDisplayName updateInline />
                </div>

                <div className="flex flex-col">
                    <h3 className="font-semibold mb-2">Business model</h3>
                    <TeamBusinessModel bare />
                </div>

                <div className="flex flex-col">
                    <h3 className="font-semibold mb-2">Timezone</h3>
                    <TeamTimezone displayWarning={false} />
                </div>
            </div>
        </OnboardingStep>
    )
}

import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingVerificationStep = ({
    listeningForName,
    teamPropertyToVerify,
    stepKey = OnboardingStepKey.VERIFY,
}: {
    listeningForName: string
    teamPropertyToVerify: string
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)
    const { openSupportForm } = useActions(supportLogic)

    useInterval(() => {
        if (!currentTeam?.[teamPropertyToVerify]) {
            loadCurrentTeam()
        }
    }, 2000)

    return !currentTeam?.[teamPropertyToVerify] ? (
        <OnboardingStep
            title={`Listening for ${listeningForName}s...`}
            subtitle={`We're verifying that you've integrated the snippet and are sending ${listeningForName}s to PostHog. It can take up to 2 minutes to recieve an ${listeningForName}.`}
            showSkip={true}
            stepKey={stepKey}
            onSkip={() => {
                reportIngestionContinueWithoutVerifying()
            }}
            continueOverride={<></>}
            helpButton={
                <LemonButton
                    type="secondary"
                    onClick={() => openSupportForm({ kind: 'support', target_area: 'onboarding' })}
                >
                    Need help?
                </LemonButton>
            }
        >
            <>
                <div className="text-center mt-8">
                    <Spinner className="text-5xl" />
                </div>
            </>
        </OnboardingStep>
    ) : (
        <OnboardingStep
            title={`${capitalizeFirstLetter(listeningForName)}s successfully sent!`}
            subtitle={`Your ${listeningForName.toLocaleLowerCase()}s will now be available in PostHog. Use them to unlock your product and data superpowers.`}
            stepKey={stepKey}
        >
            <div className="w-40 mx-auto">
                <BlushingHog className="h-full w-full" />
            </div>
        </OnboardingStep>
    )
}

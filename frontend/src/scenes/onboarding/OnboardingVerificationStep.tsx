import { Spinner } from '@posthog/lemon-ui'
import { OnboardingStep } from './OnboardingStep'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { BlushingHog } from 'lib/components/hedgehogs'
import { capitalizeFirstLetter } from 'lib/utils'
import { OnboardingStepKey } from './onboardingLogic'

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

    useInterval(() => {
        if (!currentTeam?.[teamPropertyToVerify]) {
            loadCurrentTeam()
        }
    }, 2000)

    return !currentTeam?.[teamPropertyToVerify] ? (
        <OnboardingStep
            title={`Listening for ${listeningForName}s...`}
            subtitle={`Once you have integrated the snippet, we will verify the ${listeningForName} was properly received. It can take up to 2 minutes to recieve the ${listeningForName}.`}
            showSkip={true}
            stepKey={stepKey}
            onSkip={() => {
                reportIngestionContinueWithoutVerifying()
            }}
            continueOverride={<></>}
        >
            <div className="text-center mt-8">
                <Spinner className="text-5xl" />
            </div>
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

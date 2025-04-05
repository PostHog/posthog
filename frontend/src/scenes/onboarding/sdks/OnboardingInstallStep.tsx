import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SDKInstructionsMap } from '~/types'

import { OnboardingStepKey } from '../onboardingLogic'
import { AlternativeSDKs } from './AlternativeSDKs'
import { SDKs } from './SDKs'

export type SDKsProps = {
    sdkInstructionMap: SDKInstructionsMap
    stepKey?: OnboardingStepKey
    listeningForName?: string
    teamPropertyToVerify?: string
}

export const OnboardingInstallStep = (props: SDKsProps): JSX.Element => {
    const showNewInstallationStep = useFeatureFlag('ONBOARDING_NEW_INSTALLATION_STEP', 'test')
    return showNewInstallationStep ? <AlternativeSDKs {...props} /> : <SDKs {...props} />
}

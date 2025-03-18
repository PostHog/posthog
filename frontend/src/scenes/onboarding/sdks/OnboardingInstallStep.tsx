import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { OnboardingStepProps } from '../OnboardingStep'
import { AlternativeSDKs } from './AlternativeSDKs'
import { SDKs, type SDKsProps } from './SDKs'

export type OnboardingInstallStepProps = Pick<OnboardingStepProps, 'onContinue' | 'subtitle'>

export const OnboardingInstallStep = (props: SDKsProps & OnboardingInstallStepProps): JSX.Element => {
    const showNewInstallationStep = useFeatureFlag('ONBOARDING_NEW_INSTALLATION_STEP', 'test')
    return showNewInstallationStep ? <AlternativeSDKs {...props} /> : <SDKs {...props} />
}

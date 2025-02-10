import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AlternativeSDKs } from './AlternativeSDKs'
import { SDKs, type SDKsProps } from './SDKs'

export const OnboardingInstallStep = (props: SDKsProps): JSX.Element => {
    const showNewInstallationStep = useFeatureFlag('ONBOARDING_NEW_INSTALLATION_STEP', 'test')
    return showNewInstallationStep ? <AlternativeSDKs {...props} /> : <SDKs {...props} />
}

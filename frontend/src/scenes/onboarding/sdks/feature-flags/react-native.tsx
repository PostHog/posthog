import { SDKKey } from '~/types'

import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions hideWizard />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT_NATIVE} />
            <AdvertiseMobileReplay context="flags-onboarding" sdkKey={SDKKey.REACT_NATIVE} />
        </>
    )
}

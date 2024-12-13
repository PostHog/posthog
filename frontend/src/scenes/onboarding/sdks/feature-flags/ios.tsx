import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.IOS} />
            <AdvertiseMobileReplay context="flags-onboarding" sdkKey={SDKKey.IOS} />
        </>
    )
}

import { SDKKey } from '~/types'

import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsFlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.FLUTTER} />
            <AdvertiseMobileReplay context="flags-onboarding" sdkKey={SDKKey.FLUTTER} />
        </>
    )
}

import { SDKKey } from '~/types'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.ANDROID} />
            <AdvertiseMobileReplay context="flags-onboarding" sdkKey={SDKKey.ANDROID} />
        </>
    )
}

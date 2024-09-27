import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

import { SDKKey } from '~/types'

import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.REACT_NATIVE} />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseMobileReplay context="flags-onboarding" sdkKey={SDKKey.REACT_NATIVE} />
            </FlaggedFeature>
        </>
    )
}

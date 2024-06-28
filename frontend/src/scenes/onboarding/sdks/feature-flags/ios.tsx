import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { AdvertiseiOSReplay } from 'scenes/onboarding/sdks/product-analytics'

import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.IOS} />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseiOSReplay context="product-analytics-onboarding" />
            </FlaggedFeature>
        </>
    )
}

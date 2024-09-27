import { AdvertiseiOSReplay } from 'scenes/onboarding/sdks/product-analytics'

import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.IOS} />
            <AdvertiseiOSReplay context="product-analytics-onboarding" />
        </>
    )
}

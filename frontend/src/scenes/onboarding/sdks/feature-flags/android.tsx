import { AdvertiseAndroidReplay } from 'scenes/onboarding/sdks/product-analytics'

import { SDKKey } from '~/types'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.ANDROID} />
            <AdvertiseAndroidReplay context="flags-onboarding" />
        </>
    )
}

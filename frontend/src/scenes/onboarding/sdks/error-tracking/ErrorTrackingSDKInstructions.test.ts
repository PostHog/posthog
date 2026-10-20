import { SDKKey } from '~/types'

import { ALL_SDKS } from '../allSDKs'
import { getAvailableSDKs } from '../getAvailableSDKs'
import { ErrorTrackingSDKDocsLinkOverrides, ErrorTrackingSDKInstructions } from './ErrorTrackingSDKInstructions'

describe('ErrorTrackingSDKInstructions', () => {
    const newlySupportedSDKs: Array<[SDKKey, string]> = [
        [SDKKey.RUST, 'https://posthog.com/docs/error-tracking/installation/rust'],
        [SDKKey.UNITY, 'https://posthog.com/docs/error-tracking/installation/unity'],
        [SDKKey.ROBLOX, 'https://posthog.com/docs/error-tracking/installation/roblox'],
        [SDKKey.JAVA, 'https://posthog.com/docs/libraries/java'],
        [SDKKey.KMP, 'https://posthog.com/docs/libraries/kmp'],
        [SDKKey.CONVEX, 'https://posthog.com/docs/libraries/convex'],
    ]

    it.each(newlySupportedSDKs)('makes %s selectable with working instructions and docs', (sdkKey, docsLink) => {
        const availableSDKs = getAvailableSDKs(ErrorTrackingSDKInstructions, {}, ErrorTrackingSDKDocsLinkOverrides)
        const sdk = availableSDKs.find(({ key }) => key === sdkKey)

        expect(ErrorTrackingSDKInstructions[sdkKey]).not.toBeUndefined()
        expect(sdk).toMatchObject({ key: sdkKey, docsLink })
    })

    it('keeps the AI observability link in shared Convex metadata', () => {
        expect(ALL_SDKS.find(({ key }) => key === SDKKey.CONVEX)?.docsLink).toBe(
            'https://posthog.com/docs/ai-observability/installation/convex'
        )
    })
})

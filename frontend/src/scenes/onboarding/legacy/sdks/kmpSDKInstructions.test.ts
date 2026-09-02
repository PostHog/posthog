import { SDK_CONFIGS } from 'scenes/settings/environment/SDKSetupInstructions'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsSDKInstructions } from './experiments/ExperimentsSDKInstructions'
import { FeatureFlagsSDKInstructions } from './feature-flags/FeatureFlagsSDKInstructions'
import { getAvailableSDKs } from './getAvailableSDKs'
import { ProductAnalyticsSDKInstructions } from './product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from './session-replay/SessionReplaySDKInstructions'
import { WebAnalyticsSDKInstructions } from './web-analytics/WebAnalyticsSDKInstructions'

const KMP_DOCS_LINK = 'https://posthog.com/docs/libraries/kmp'

describe('Kotlin Multiplatform onboarding', () => {
    const productsSupportingKMP: Array<[string, SDKInstructionsMap]> = [
        ['product analytics', ProductAnalyticsSDKInstructions],
        ['session replay', SessionReplaySDKInstructions],
        ['feature flags', FeatureFlagsSDKInstructions],
        ['experiments', ExperimentsSDKInstructions],
        ['web analytics', WebAnalyticsSDKInstructions],
    ]

    it.each(productsSupportingKMP)('makes KMP selectable in %s onboarding', (_product, instructions) => {
        const sdk = getAvailableSDKs(instructions, {}, {}).find(({ key }) => key === SDKKey.KMP)

        expect(instructions[SDKKey.KMP]).not.toBeUndefined()
        expect(sdk).toMatchObject({ key: SDKKey.KMP, docsLink: KMP_DOCS_LINK })
    })

    it('lists KMP as a mobile SDK in the SDK setup picker', () => {
        expect(SDK_CONFIGS[SDKKey.KMP]).toMatchObject({
            name: 'Kotlin Multiplatform',
            docsLink: KMP_DOCS_LINK,
            category: 'mobile',
        })
    })
})

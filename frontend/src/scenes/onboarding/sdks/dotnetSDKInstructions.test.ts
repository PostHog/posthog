import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsSDKInstructions } from './experiments/ExperimentsSDKInstructions'
import { FeatureFlagsSDKInstructions } from './feature-flags/FeatureFlagsSDKInstructions'
import { getAvailableSDKs } from './getAvailableSDKs'
import { ProductAnalyticsSDKInstructions } from './product-analytics/ProductAnalyticsSDKInstructions'

describe('.NET onboarding', () => {
    const productInstructions: Array<[string, SDKInstructionsMap]> = [
        ['Product analytics', ProductAnalyticsSDKInstructions],
        ['Feature flags', FeatureFlagsSDKInstructions],
        ['Experiments', ExperimentsSDKInstructions],
    ]

    it.each(productInstructions)('makes .NET selectable in %s onboarding', (_, instructions) => {
        const sdk = getAvailableSDKs(instructions, {}, {}).find(({ key }) => key === SDKKey.DOTNET)

        expect(instructions[SDKKey.DOTNET]).not.toBeUndefined()
        expect(sdk).toMatchObject({ key: SDKKey.DOTNET, docsLink: 'https://posthog.com/docs/libraries/dotnet' })
    })
})

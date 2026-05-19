import { ALL_SDKS } from 'scenes/onboarding/sdks/allSDKs'

import { SDKKey } from '~/types'

import { ErrorTrackingSDKInstructions } from './ErrorTrackingSDKInstructions'

jest.mock('scenes/onboarding/sdks/shared/onboardingWrappers', () => ({
    withOnboardingDocsWrapper: ({ Installation }: { Installation: unknown }) => Installation,
}))

describe('ErrorTrackingSDKInstructions', () => {
    it('includes supported server SDKs in the onboarding SDK registry', () => {
        const supportedSDKKeys = [SDKKey.GO, SDKKey.PHP, SDKKey.ELIXIR, SDKKey.DOTNET]
        const registeredSDKKeys = new Set(ALL_SDKS.map((sdk) => sdk.key))

        for (const sdkKey of supportedSDKKeys) {
            expect(ErrorTrackingSDKInstructions[sdkKey]).not.toBeUndefined()
            expect(registeredSDKKeys.has(sdkKey)).toBe(true)
        }
    })
})

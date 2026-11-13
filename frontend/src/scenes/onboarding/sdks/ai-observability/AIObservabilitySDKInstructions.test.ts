import { SDKKey, SDKTag } from '~/types'

import { getAvailableSDKs } from '../getAvailableSDKs'
import { AIObservabilitySDKInstructions, AIObservabilitySDKTagOverrides } from './AIObservabilitySDKInstructions'

describe('AIObservabilitySDKInstructions', () => {
    const newlySupportedSDKs: Array<[SDKKey, string, SDKTag[]]> = [
        [SDKKey.EDEN_AI, 'https://posthog.com/docs/ai-observability/installation/eden-ai', [SDKTag.GATEWAY]],
    ]

    it.each(newlySupportedSDKs)('makes %s selectable with working instructions and docs', (sdkKey, docsLink, tags) => {
        const availableSDKs = getAvailableSDKs(AIObservabilitySDKInstructions, AIObservabilitySDKTagOverrides, {})
        const sdk = availableSDKs.find(({ key }) => key === sdkKey)

        expect(AIObservabilitySDKInstructions[sdkKey]).not.toBeUndefined()
        expect(sdk).toMatchObject({ key: sdkKey, docsLink, tags })
    })
})

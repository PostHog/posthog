import { isKeyOf } from 'lib/utils/guards'

import { SDK, SDKDocsLinkOverrides, SDKInstructionsMap, SDKTag, SDKTagOverrides } from '~/types'

import { ALL_SDKS } from './allSDKs'

export const getAvailableSDKs = (
    availableSDKInstructionsMap: SDKInstructionsMap,
    sdkTagOverrides: SDKTagOverrides,
    sdkDocsLinkOverrides: SDKDocsLinkOverrides
): SDK[] => {
    const availableSDKKeys = Object.keys(availableSDKInstructionsMap)
    return ALL_SDKS.filter((sdk) => availableSDKKeys.includes(sdk.key)).map((sdk) => ({
        ...sdk,
        ...(isKeyOf(sdk.key, sdkTagOverrides) ? { tags: sdkTagOverrides[sdk.key] as SDKTag[] } : {}),
        ...(isKeyOf(sdk.key, sdkDocsLinkOverrides) ? { docsLink: sdkDocsLinkOverrides[sdk.key] as string } : {}),
    }))
}

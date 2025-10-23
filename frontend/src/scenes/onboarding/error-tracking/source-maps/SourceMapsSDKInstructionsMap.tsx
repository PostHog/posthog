import { allSDKs } from 'scenes/onboarding/sdks/allSDKs'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { NextJSSourceMapsInstructions } from './automated-technologies/NextJSSourceMapsInstructions'
import { NuxtSourceMapsInstructions } from './automated-technologies/NuxtSourceMapsInstructions'

export const SourceMapsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.NEXT_JS]: NextJSSourceMapsInstructions,
    [SDKKey.NUXT_JS]: NuxtSourceMapsInstructions,
}

export const automatedSourceMapsTechnologies = allSDKs.filter((sdk) =>
    [SDKKey.NEXT_JS, SDKKey.NUXT_JS].includes(sdk.key as SDKKey)
)

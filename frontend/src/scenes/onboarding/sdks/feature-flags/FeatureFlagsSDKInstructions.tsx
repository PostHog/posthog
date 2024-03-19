import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    FeatureFlagsAndroidInstructions,
    FeatureFlagsAngularInstructions,
    FeatureFlagsAPIInstructions,
    FeatureFlagsAstroInstructions,
    FeatureFlagsFlutterInstructions,
    FeatureFlagsGoInstructions,
    FeatureFlagsIOSInstructions,
    FeatureFlagsJSWebInstructions,
    FeatureFlagsNextJSInstructions,
    FeatureFlagsNodeInstructions,
    FeatureFlagsPHPInstructions,
    FeatureFlagsPythonInstructions,
    FeatureFlagsReactInstructions,
    FeatureFlagsRNInstructions,
    FeatureFlagsRubyInstructions,
} from '.'

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: FeatureFlagsJSWebInstructions,
    [SDKKey.ANGULAR]: FeatureFlagsAngularInstructions,
    [SDKKey.ANDROID]: FeatureFlagsAndroidInstructions,
    [SDKKey.API]: FeatureFlagsAPIInstructions,
    [SDKKey.ASTRO]: FeatureFlagsAstroInstructions,
    [SDKKey.FLUTTER]: FeatureFlagsFlutterInstructions,
    [SDKKey.GO]: FeatureFlagsGoInstructions,
    [SDKKey.IOS]: FeatureFlagsIOSInstructions,
    [SDKKey.NEXT_JS]: FeatureFlagsNextJSInstructions,
    [SDKKey.NODE_JS]: FeatureFlagsNodeInstructions,
    [SDKKey.PHP]: FeatureFlagsPHPInstructions,
    [SDKKey.PYTHON]: FeatureFlagsPythonInstructions,
    [SDKKey.REACT]: FeatureFlagsReactInstructions,
    [SDKKey.REACT_NATIVE]: FeatureFlagsRNInstructions,
    [SDKKey.RUBY]: FeatureFlagsRubyInstructions,
    // add rust, gatsby, nuxt, vue, svelte, and others here
}

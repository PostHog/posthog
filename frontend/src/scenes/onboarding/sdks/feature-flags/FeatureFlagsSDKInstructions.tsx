import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    FeatureFlagsAndroidInstructions,
    FeatureFlagsAngularInstructions,
    FeatureFlagsAPIInstructions,
    FeatureFlagsAstroInstructions,
    FeatureFlagsBubbleInstructions,
    FeatureFlagsFlutterInstructions,
    FeatureFlagsFramerInstructions,
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
    [SDKKey.BUBBLE]: FeatureFlagsBubbleInstructions,
    [SDKKey.FLUTTER]: FeatureFlagsFlutterInstructions,
    [SDKKey.FRAMER]: FeatureFlagsFramerInstructions,
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

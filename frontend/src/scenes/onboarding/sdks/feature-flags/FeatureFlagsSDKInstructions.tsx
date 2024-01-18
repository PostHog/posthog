import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    FeatureFlagsAndroidInstructions,
    FeatureFlagsAPIInstructions,
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
    [SDKKey.REACT]: FeatureFlagsReactInstructions,
    [SDKKey.NEXT_JS]: FeatureFlagsNextJSInstructions,
    [SDKKey.IOS]: FeatureFlagsIOSInstructions,
    [SDKKey.REACT_NATIVE]: FeatureFlagsRNInstructions,
    [SDKKey.ANDROID]: FeatureFlagsAndroidInstructions,
    [SDKKey.FLUTTER]: FeatureFlagsFlutterInstructions,
    [SDKKey.NODE_JS]: FeatureFlagsNodeInstructions,
    [SDKKey.PYTHON]: FeatureFlagsPythonInstructions,
    [SDKKey.RUBY]: FeatureFlagsRubyInstructions,
    [SDKKey.PHP]: FeatureFlagsPHPInstructions,
    [SDKKey.GO]: FeatureFlagsGoInstructions,
    [SDKKey.API]: FeatureFlagsAPIInstructions,
    // add rust, gatsby, nuxt, vue, svelte, and others here
}

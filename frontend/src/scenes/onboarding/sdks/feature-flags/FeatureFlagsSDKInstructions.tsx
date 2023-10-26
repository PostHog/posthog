import { SDKInstructionsMap, SDKKey } from '~/types'
import {
    FeatureFlagsJSWebInstructions,
    FeatureFlagsNextJSInstructions,
    FeatureFlagsAPIInstructions,
    FeatureFlagsAndroidInstructions,
    FeatureFlagsGoInstructions,
    FeatureFlagsIOSInstructions,
    FeatureFlagsNodeInstructions,
    FeatureFlagsPHPInstructions,
    FeatureFlagsPythonInstructions,
    FeatureFlagsRNInstructions,
    FeatureFlagsRubyInstructions,
    FeatureFlagsReactInstructions,
} from '.'

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: FeatureFlagsJSWebInstructions,
    [SDKKey.REACT]: FeatureFlagsReactInstructions,
    [SDKKey.NEXT_JS]: FeatureFlagsNextJSInstructions,
    [SDKKey.IOS]: FeatureFlagsIOSInstructions,
    [SDKKey.REACT_NATIVE]: FeatureFlagsRNInstructions,
    [SDKKey.ANDROID]: FeatureFlagsAndroidInstructions,
    [SDKKey.NODE_JS]: FeatureFlagsNodeInstructions,
    [SDKKey.PYTHON]: FeatureFlagsPythonInstructions,
    [SDKKey.RUBY]: FeatureFlagsRubyInstructions,
    [SDKKey.PHP]: FeatureFlagsPHPInstructions,
    [SDKKey.GO]: FeatureFlagsGoInstructions,
    [SDKKey.API]: FeatureFlagsAPIInstructions,
    // add flutter, rust, gatsby, nuxt, vue, svelte, and others here
}

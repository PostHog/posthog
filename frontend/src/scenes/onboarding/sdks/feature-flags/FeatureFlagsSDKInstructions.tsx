import { SDKInstructionsMap, SDKKey } from '~/types'
import {
    JSWebInstructions,
    NextJSInstructions,
    ProductAnalyticsAPIInstructions,
    ProductAnalyticsAndroidInstructions,
    ProductAnalyticsGoInstructions,
    ProductAnalyticsIOSInstructions,
    ProductAnalyticsNodeInstructions,
    ProductAnalyticsPHPInstructions,
    ProductAnalyticsPythonInstructions,
    ProductAnalyticsRNInstructions,
    ProductAnalyticsRubyInstructions,
    ReactInstructions,
} from '.'

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.IOS]: ProductAnalyticsIOSInstructions,
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructions,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructions,
    [SDKKey.NODE_JS]: ProductAnalyticsNodeInstructions,
    [SDKKey.PYTHON]: ProductAnalyticsPythonInstructions,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructions,
    [SDKKey.PHP]: ProductAnalyticsPHPInstructions,
    [SDKKey.GO]: ProductAnalyticsGoInstructions,
    [SDKKey.API]: ProductAnalyticsAPIInstructions,
    // add flutter, rust, gatsby, nuxt, vue, svelte, and others here
}

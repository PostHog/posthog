import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    HTMLSnippetInstructions,
    JSWebInstructions,
    ProductAnalyticsAndroidInstructions,
    ProductAnalyticsAPIInstructions,
    ProductAnalyticsElixirInstructions,
    ProductAnalyticsFlutterInstructions,
    ProductAnalyticsGoInstructions,
    ProductAnalyticsIOSInstructions,
    ProductAnalyticsNodeInstructions,
    ProductAnalyticsPHPInstructions,
    ProductAnalyticsPythonInstructions,
    ProductAnalyticsRNInstructions,
    ProductAnalyticsRubyInstructions,
} from '.'

export const ProductAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    // add next, getsby, and others here
    [SDKKey.IOS]: ProductAnalyticsIOSInstructions,
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructions,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructions,
    [SDKKey.FLUTTER]: ProductAnalyticsFlutterInstructions,
    [SDKKey.NODE_JS]: ProductAnalyticsNodeInstructions,
    [SDKKey.PYTHON]: ProductAnalyticsPythonInstructions,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructions,
    [SDKKey.PHP]: ProductAnalyticsPHPInstructions,
    [SDKKey.GO]: ProductAnalyticsGoInstructions,
    [SDKKey.ELIXIR]: ProductAnalyticsElixirInstructions,
    [SDKKey.API]: ProductAnalyticsAPIInstructions,
}

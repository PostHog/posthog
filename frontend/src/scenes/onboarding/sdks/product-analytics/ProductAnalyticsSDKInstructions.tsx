import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    HTMLSnippetInstructions,
    JSWebInstructions,
    ProductAnalyticsAndroidInstructions,
    ProductAnalyticsAngularInstructions,
    ProductAnalyticsAPIInstructions,
    ProductAnalyticsAstroInstructions,
    ProductAnalyticsElixirInstructions,
    ProductAnalyticsFlutterInstructions,
    ProductAnalyticsGoInstructions,
    ProductAnalyticsIOSInstructions,
    ProductAnalyticsNextJSInstructions,
    ProductAnalyticsNodeInstructions,
    ProductAnalyticsPHPInstructions,
    ProductAnalyticsPythonInstructions,
    ProductAnalyticsRNInstructions,
    ProductAnalyticsRubyInstructions,
} from '.'

export const ProductAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructions,
    [SDKKey.ANGULAR]: ProductAnalyticsAngularInstructions,
    [SDKKey.API]: ProductAnalyticsAPIInstructions,
    [SDKKey.ASTRO]: ProductAnalyticsAstroInstructions,
    [SDKKey.ELIXIR]: ProductAnalyticsElixirInstructions,
    [SDKKey.FLUTTER]: ProductAnalyticsFlutterInstructions,
    [SDKKey.GO]: ProductAnalyticsGoInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.IOS]: ProductAnalyticsIOSInstructions,
    [SDKKey.NEXT_JS]: ProductAnalyticsNextJSInstructions,
    [SDKKey.NODE_JS]: ProductAnalyticsNodeInstructions,
    [SDKKey.PHP]: ProductAnalyticsPHPInstructions,
    [SDKKey.PYTHON]: ProductAnalyticsPythonInstructions,
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructions,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructions,
}

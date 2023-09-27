import { SDKInstructionsMap, SDKKey } from '~/types'
import {
    JSWebInstructions,
    ProductAnalyticsAPIInstructions,
    ProductAnalyticsAndroidInstructions,
    ProductAnalyticsGoInstructions,
    ProductAnalyticsIOSInstructions,
    ProductAnalyticsNodeInstructions,
    ProductAnalyticsPHPInstructions,
    ProductAnalyticsPythonInstructions,
    ProductAnalyticsRNInstructions,
    ProductAnalyticsRubyInstructions,
} from '.'
import { ReactInstructions } from './react'

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.REACT]: ReactInstructions,
    // add next, gatsby, and others here
    [SDKKey.IOS]: ProductAnalyticsIOSInstructions,
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructions,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructions,
    [SDKKey.NODE_JS]: ProductAnalyticsNodeInstructions,
    [SDKKey.PYTHON]: ProductAnalyticsPythonInstructions,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructions,
    [SDKKey.PHP]: ProductAnalyticsPHPInstructions,
    [SDKKey.GO]: ProductAnalyticsGoInstructions,
    [SDKKey.API]: ProductAnalyticsAPIInstructions,
}

import {
    AngularInstructions,
    AstroInstructions,
    BubbleInstructions,
    FlutterInstructions,
    FramerInstructions,
    HTMLSnippetInstructions,
    JSWebInstructions,
    NextJSInstructions,
    NuxtJSInstructions,
    RNInstructions,
    ReactInstructions,
    RemixInstructions,
    SvelteInstructions,
    VueInstructions,
    WebflowInstructions,
    iOSInstructions,
} from '.'

import { SDKInstructionsMap, SDKKey } from '~/types'

export const SurveysSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.ASTRO]: AstroInstructions,
    [SDKKey.BUBBLE]: BubbleInstructions,
    [SDKKey.FRAMER]: FramerInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.NUXT_JS]: NuxtJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.REMIX]: RemixInstructions,
    [SDKKey.SVELTE]: SvelteInstructions,
    [SDKKey.VUE_JS]: VueInstructions,
    [SDKKey.WEBFLOW]: WebflowInstructions,
    [SDKKey.IOS]: iOSInstructions,
    [SDKKey.FLUTTER]: FlutterInstructions,
    [SDKKey.REACT_NATIVE]: RNInstructions,
}

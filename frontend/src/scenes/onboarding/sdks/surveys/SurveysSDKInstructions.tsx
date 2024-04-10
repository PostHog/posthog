import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AngularInstructions,
    AstroInstructions,
    BubbleInstructions,
    FramerInstructions,
    HTMLSnippetInstructions,
    JSWebInstructions,
    NextJSInstructions,
    NuxtJSInstructions,
    ReactInstructions,
    RemixInstructions,
    SvelteInstructions,
    VueInstructions,
    WebflowInstructions,
} from '.'

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
}

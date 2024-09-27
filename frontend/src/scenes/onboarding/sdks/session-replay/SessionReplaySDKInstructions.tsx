import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AndroidInstructions,
    AngularInstructions,
    AstroInstructions,
    BubbleInstructions,
    FramerInstructions,
    HTMLSnippetInstructions,
    iOSInstructions,
    JSWebInstructions,
    NextJSInstructions,
    NuxtJSInstructions,
    ReactInstructions,
    RemixInstructions,
    SvelteInstructions,
    VueInstructions,
    WebflowInstructions,
} from '.'
import { RNInstructions } from './react-native'

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
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
    [SDKKey.ANDROID]: AndroidInstructions,
    [SDKKey.REACT_NATIVE]: RNInstructions,
}

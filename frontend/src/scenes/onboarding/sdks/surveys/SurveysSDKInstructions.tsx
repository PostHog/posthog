import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AngularInstructions,
    AstroInstructions,
    BubbleInstructions,
    FramerInstructions,
    HTMLSnippetInstructions,
    JSWebInstructions,
    NextJSInstructions,
    ReactInstructions,
} from '.'

export const SurveysSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.ASTRO]: AstroInstructions,
    [SDKKey.BUBBLE]: BubbleInstructions,
    [SDKKey.FRAMER]: FramerInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
}

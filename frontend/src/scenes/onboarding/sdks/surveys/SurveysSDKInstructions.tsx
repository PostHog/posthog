import { SDKInstructionsMap, SDKKey } from '~/types'

import { HTMLSnippetInstructions, JSWebInstructions, NextJSInstructions, ReactInstructions, AngularInstructions } from '.'

export const SurveysSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
}

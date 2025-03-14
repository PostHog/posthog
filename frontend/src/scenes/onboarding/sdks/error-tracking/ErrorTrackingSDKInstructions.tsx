import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AngularInstructions,
    HTMLSnippetInstructions,
    JSWebInstructions,
    NextJSInstructions,
    NodeInstructions,
    PythonInstructions,
    ReactInstructions,
    SvelteInstructions,
} from '.'

export const ErrorTrackingSDKInstructions: SDKInstructionsMap = {
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.PYTHON]: PythonInstructions,
    [SDKKey.NODE_JS]: NodeInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.SVELTE]: SvelteInstructions,
    [SDKKey.ANGULAR]: AngularInstructions,
}

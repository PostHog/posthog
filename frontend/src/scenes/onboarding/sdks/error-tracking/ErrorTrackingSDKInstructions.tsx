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
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.NODE_JS]: NodeInstructions,
    [SDKKey.PYTHON]: PythonInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.SVELTE]: SvelteInstructions,
}

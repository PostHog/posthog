import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AndroidInstructions,
    HTMLSnippetInstructions,
    JSWebInstructions,
    NextJSInstructions,
    ReactInstructions,
} from '.'

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.ANDROID]: AndroidInstructions,
}

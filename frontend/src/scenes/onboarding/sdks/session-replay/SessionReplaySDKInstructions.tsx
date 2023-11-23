import { SDKInstructionsMap, SDKKey } from '~/types'

import { JSWebInstructions, NextJSInstructions, ReactInstructions } from '.'

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
}

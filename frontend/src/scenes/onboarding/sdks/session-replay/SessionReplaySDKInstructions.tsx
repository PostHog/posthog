import { SDKKey } from '~/types'
import { JSWebInstructions, NextJSInstructions } from '.'

export const SessionReplaySDKInstructions = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.REACT]: JSWebInstructions,
    [SDKKey.IOS]: JSWebInstructions,
}

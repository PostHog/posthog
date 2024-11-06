import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsGoInstructions } from './go'
import { ExperimentsJSWebInstructions } from './js-web'
import { ExperimentsNodeJSInstructions } from './nodejs'
import { ExperimentsPHPInstructions } from './php'
import { ExperimentsPythonInstructions } from './python'
import { ExperimentsReactNativeInstructions } from './react-native'
import { ExperimentsRubyInstructions } from './ruby'

export const ExperimentsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ExperimentsJSWebInstructions,
    [SDKKey.GO]: ExperimentsGoInstructions,
    [SDKKey.NODE_JS]: ExperimentsNodeJSInstructions,
    [SDKKey.PHP]: ExperimentsPHPInstructions,
    [SDKKey.PYTHON]: ExperimentsPythonInstructions,
    [SDKKey.REACT_NATIVE]: ExperimentsReactNativeInstructions,
    [SDKKey.RUBY]: ExperimentsRubyInstructions,
}

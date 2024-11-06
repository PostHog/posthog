import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsJSWebInstructions } from './js-web'
import { ExperimentsPythonInstructions } from './python'

export const ExperimentsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ExperimentsJSWebInstructions,
    [SDKKey.PYTHON]: ExperimentsPythonInstructions,
}

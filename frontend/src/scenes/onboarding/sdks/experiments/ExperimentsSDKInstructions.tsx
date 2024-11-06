import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsAngularInstructions } from './angular'
import { ExperimentsAstroInstructions } from './astro'
import { ExperimentsBubbleInstructions } from './bubble'
import { ExperimentsDjangoInstructions } from './django'
import { ExperimentsGoInstructions } from './go'
import { ExperimentsJSWebInstructions } from './js-web'
import { ExperimentsLaravelInstructions } from './laravel'
import { ExperimentsNodeJSInstructions } from './nodejs'
import { ExperimentsPHPInstructions } from './php'
import { ExperimentsPythonInstructions } from './python'
import { ExperimentsReactNativeInstructions } from './react-native'
import { ExperimentsRubyInstructions } from './ruby'

export const ExperimentsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ExperimentsJSWebInstructions,
    [SDKKey.ANGULAR]: ExperimentsAngularInstructions,
    [SDKKey.ASTRO]: ExperimentsAstroInstructions,
    [SDKKey.BUBBLE]: ExperimentsBubbleInstructions,
    [SDKKey.DJANGO]: ExperimentsDjangoInstructions,
    [SDKKey.GO]: ExperimentsGoInstructions,
    [SDKKey.LARAVEL]: ExperimentsLaravelInstructions,
    [SDKKey.NODE_JS]: ExperimentsNodeJSInstructions,
    [SDKKey.PHP]: ExperimentsPHPInstructions,
    [SDKKey.PYTHON]: ExperimentsPythonInstructions,
    [SDKKey.REACT_NATIVE]: ExperimentsReactNativeInstructions,
    [SDKKey.RUBY]: ExperimentsRubyInstructions,
}

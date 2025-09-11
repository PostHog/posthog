import { SDKInstructionsMap, SDKKey } from '~/types'

import { ExperimentsAndroidInstructions } from './android'
import { ExperimentsAngularInstructions } from './angular'
import { ExperimentsAstroInstructions } from './astro'
import { ExperimentsBubbleInstructions } from './bubble'
import { ExperimentsDjangoInstructions } from './django'
import { ExperimentsFlutterInstructions } from './flutter'
import { ExperimentsFramerInstructions } from './framer'
import { ExperimentsGoInstructions } from './go'
import { ExperimentsIOSInstructions } from './ios'
import { ExperimentsJSWebInstructions } from './js-web'
import { ExperimentsLaravelInstructions } from './laravel'
import { ExperimentsNextJSInstructions } from './next-js'
import { ExperimentsNodeJSInstructions } from './nodejs'
import { ExperimentsNuxtInstructions } from './nuxt'
import { ExperimentsPHPInstructions } from './php'
import { ExperimentsPythonInstructions } from './python'
import { ExperimentsReactInstructions } from './react'
import { ExperimentsReactNativeInstructions } from './react-native'
import { ExperimentsRemixInstructions } from './remix'
import { ExperimentsRubyInstructions } from './ruby'
import { ExperimentsSvelteInstructions } from './svelte'
import { ExperimentsVueInstructions } from './vue'
import { ExperimentsWebflowInstructions } from './webflow'

export const ExperimentsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ExperimentsJSWebInstructions,
    [SDKKey.ANDROID]: ExperimentsAndroidInstructions,
    [SDKKey.ANGULAR]: ExperimentsAngularInstructions,
    [SDKKey.ASTRO]: ExperimentsAstroInstructions,
    [SDKKey.BUBBLE]: ExperimentsBubbleInstructions,
    [SDKKey.DJANGO]: ExperimentsDjangoInstructions,
    [SDKKey.FLUTTER]: ExperimentsFlutterInstructions,
    [SDKKey.FRAMER]: ExperimentsFramerInstructions,
    [SDKKey.GO]: ExperimentsGoInstructions,
    [SDKKey.IOS]: ExperimentsIOSInstructions,
    [SDKKey.LARAVEL]: ExperimentsLaravelInstructions,
    [SDKKey.NEXT_JS]: ExperimentsNextJSInstructions,
    [SDKKey.NODE_JS]: ExperimentsNodeJSInstructions,
    [SDKKey.NUXT_JS]: ExperimentsNuxtInstructions,
    [SDKKey.PHP]: ExperimentsPHPInstructions,
    [SDKKey.PYTHON]: ExperimentsPythonInstructions,
    [SDKKey.REACT]: ExperimentsReactInstructions,
    [SDKKey.REACT_NATIVE]: ExperimentsReactNativeInstructions,
    [SDKKey.REMIX]: ExperimentsRemixInstructions,
    [SDKKey.RUBY]: ExperimentsRubyInstructions,
    [SDKKey.SVELTE]: ExperimentsSvelteInstructions,
    [SDKKey.WEBFLOW]: ExperimentsWebflowInstructions,
    [SDKKey.VUE_JS]: ExperimentsVueInstructions,
}

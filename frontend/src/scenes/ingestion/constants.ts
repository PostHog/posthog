import { PlatformType } from 'scenes/ingestion/types'

export const PLATFORM_TYPE = 'PLATFORM_TYPE'
export const AUTOCAPTURE = 'AUTOCAPTURE'
export const FRAMEWORK = 'FRAMEWORK'
export const INSTRUCTIONS = 'INSTRUCTIONS'
export const VERIFICATION = 'VERIFICATION'

export const WEB = 'Web'
export const MOBILE = 'Mobile'
export const BACKEND = 'Backend'
export const platforms = [WEB, MOBILE, BACKEND]

export const PURE_JS = 'PURE_JS'
export const NODEJS = 'NODEJS'
export const GO = 'GO'
export const RUBY = 'RUBY'
export const PYTHON = 'PYTHON'
export const PHP = 'PHP'
export const ELIXIR = 'ELIXIR'
export const API = 'API'

export const ANDROID = 'ANDROID'
export const IOS = 'IOS'
export const REACT_NATIVE = 'REACT_NATIVE'
export const FLUTTER = 'FLUTTER'

export const frameworkToPlatform = (framework: string): PlatformType => {
    switch (framework) {
        case PURE_JS:
        case AUTOCAPTURE:
            return WEB
        case NODEJS:
        case GO:
        case RUBY:
        case PYTHON:
        case PHP:
        case ELIXIR:
            return BACKEND
        case API:
        // ??
        case ANDROID:
        case IOS:
        case FLUTTER:
        case REACT_NATIVE:
            return MOBILE
    }
    return null
}

export const httpFrameworks = {
    [API]: 'HTTP API',
}
export const webFrameworks = {
    [NODEJS]: 'Node.js',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
    [ELIXIR]: 'Elixir',
    ...httpFrameworks,
}

export const mobileFrameworks = {
    [ANDROID]: 'Android',
    [IOS]: 'iOS',
    [REACT_NATIVE]: 'React Native',
    [FLUTTER]: 'Flutter',
    ...httpFrameworks,
}

// todo: replace web w/ server, rename client to web.
export const clientFrameworks = {
    [PURE_JS]: 'JavaScript SDK',
    [AUTOCAPTURE]: 'JavaScript Snippet',
    ...httpFrameworks,
}

export const allFrameworks = {
    ...webFrameworks,
    ...clientFrameworks,
    ...mobileFrameworks,
    ...httpFrameworks,
}

export const popularFrameworks = {
    [AUTOCAPTURE]: clientFrameworks[AUTOCAPTURE],
    [PURE_JS]: clientFrameworks[PURE_JS],
    [NODEJS]: webFrameworks[NODEJS],
    [PYTHON]: webFrameworks[PYTHON],
    [GO]: webFrameworks[GO],
    [RUBY]: webFrameworks[RUBY],
    [ANDROID]: mobileFrameworks[ANDROID],
    [IOS]: mobileFrameworks[IOS],
    [REACT_NATIVE]: mobileFrameworks[REACT_NATIVE],
    [API]: httpFrameworks[API],
}

import testLogo from './panels/test-logo.svg'
import flutterLogo from './panels/flutter_logo.png'
import nodeJSLogo from './panels/nodejs-logo.png'
import nodeJSLogo2 from './panels/nodejs2.svg'
import rubyLogo from './panels/ruby-logo.png'
import jsLogo from './panels/js-logo.png'
import pythonLogo from './panels/python-logo.svg'
// import pythonLogo from './panels/python-logo.png'
import phpLogo from './panels/php-logo.svg'
import elixirLogo from './panels/elixir-logo.svg'
import goLogo from './panels/go-logo-blue.svg'
import reactLogo from './panels/react-logo.svg'
import androidLogo from './panels/android-logo.svg'
import appleLogo from './panels/apple-logo.svg'
import posthogLogo from './panels/posthog-logo.svg'
import bashLogo from './panels/bash-logo.svg'

export const logos = {
    [NODEJS]: nodeJSLogo2,
    [FLUTTER]: flutterLogo,
    [PURE_JS]: testLogo,
    [RUBY]: rubyLogo,
    [PURE_JS]: jsLogo,
    // todo: maybe it's fine to use the same logo since they both go to the same instructions.
    [AUTOCAPTURE]: posthogLogo,
    [PYTHON]: pythonLogo,
    [PHP]: phpLogo,
    [ELIXIR]: elixirLogo,
    [GO]: goLogo,
    [REACT_NATIVE]: reactLogo,
    [ANDROID]: androidLogo,
    [IOS]: appleLogo,
    [API]: bashLogo,
    default: nodeJSLogo,
}

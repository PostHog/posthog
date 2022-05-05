import { Framework, PlatformType } from 'scenes/ingestion/types'

import flutterLogo from './static/flutter_logo.png'
import nodeJSLogo from './static/nodejs-logo.svg'
import rubyLogo from './static/ruby-logo.png'
import jsLogo from './static/js-logo.png'
import pythonLogo from './static/python-logo.svg'
import phpLogo from './static/php-logo.svg'
import elixirLogo from './static/elixir-logo.svg'
import goLogo from './static/go-logo-blue.svg'
import reactLogo from './static/react-logo.svg'
import androidLogo from './static/android-logo.svg'
import appleLogo from './static/apple-logo.svg'
import posthogLogo from './static/posthog-logo.svg'
import bashLogo from './static/bash-logo.svg'
import React from 'react'
import { Segment } from './panels/ThirdPartyIcons'

export const PLATFORM_TYPE = 'PLATFORM_TYPE'
export const AUTOCAPTURE = 'AUTOCAPTURE'
export const FRAMEWORK = 'FRAMEWORK'
export const INSTRUCTIONS = 'INSTRUCTIONS'
export const VERIFICATION = 'VERIFICATION'

export const WEB = 'Web'
export const MOBILE = 'Mobile'
export const BACKEND = 'Backend'
export const THIRD_PARTY = 'Import events from a third party'
export const BOOKMARKLET = 'Just exploring?'
export const platforms: PlatformType[] = [WEB, MOBILE, BACKEND]

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

export const frameworkToPlatform = (framework: Framework): PlatformType => {
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
}

export const mobileFrameworks = {
    [ANDROID]: 'Android',
    [IOS]: 'iOS',
    [REACT_NATIVE]: 'React Native',
    [FLUTTER]: 'Flutter',
}

export const clientFrameworks = {
    [PURE_JS]: 'JavaScript SDK',
    [AUTOCAPTURE]: 'JavaScript Snippet',
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
export const logos = {
    [NODEJS]: nodeJSLogo,
    [FLUTTER]: flutterLogo,
    [RUBY]: rubyLogo,
    [PURE_JS]: jsLogo,
    [AUTOCAPTURE]: posthogLogo,
    [PYTHON]: pythonLogo,
    [PHP]: phpLogo,
    [ELIXIR]: elixirLogo,
    [GO]: goLogo,
    [REACT_NATIVE]: reactLogo,
    [ANDROID]: androidLogo,
    [IOS]: appleLogo,
    [API]: bashLogo,
    default: posthogLogo,
}

export enum ThirdPartySourceType {
    Integration = 'INTEGRATION',
    Plugin = 'PLUGIN',
}

export const thirdPartySources = [
    {
        name: 'Segment',
        type: ThirdPartySourceType.Integration,
        icon: <Segment />,
        docsLink: 'https://segment.com/docs/connections/destinations/catalog/posthog/',
    },
    {
        name: 'Rudderstack',
        type: ThirdPartySourceType.Integration,
        icon: (
            <img
                style={{ height: 36, width: 36 }}
                src={'https://raw.githubusercontent.com/rudderlabs/rudderstack-posthog-plugin/main/logo.png'}
            />
        ),
        docsLink: 'https://www.rudderstack.com/docs/destinations/analytics/posthog/',
    },
    {
        name: 'Redshift',
        type: ThirdPartySourceType.Plugin,
        pluginName: 'redshift-import-plugin-(beta)',
        icon: (
            <img
                style={{ height: 48, width: 48 }}
                src={'https://raw.githubusercontent.com/PostHog/posthog-redshift-import-plugin/main/logo.png'}
            />
        ),
    },
]

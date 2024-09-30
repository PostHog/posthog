import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingStepKey } from 'scenes/onboarding/onboardingLogic'
import { urls } from 'scenes/urls'

import { SDKInstructionsMap, SDKKey } from '~/types'

import {
    AndroidInstructions,
    AngularInstructions,
    AstroInstructions,
    BubbleInstructions,
    FramerInstructions,
    HTMLSnippetInstructions,
    iOSInstructions,
    JSWebInstructions,
    NextJSInstructions,
    NuxtJSInstructions,
    ReactInstructions,
    RemixInstructions,
    SvelteInstructions,
    VueInstructions,
    WebflowInstructions,
} from '.'
import { RNInstructions } from './react-native'

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: JSWebInstructions,
    [SDKKey.HTML_SNIPPET]: HTMLSnippetInstructions,
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.ASTRO]: AstroInstructions,
    [SDKKey.BUBBLE]: BubbleInstructions,
    [SDKKey.FRAMER]: FramerInstructions,
    [SDKKey.NEXT_JS]: NextJSInstructions,
    [SDKKey.NUXT_JS]: NuxtJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.REMIX]: RemixInstructions,
    [SDKKey.SVELTE]: SvelteInstructions,
    [SDKKey.VUE_JS]: VueInstructions,
    [SDKKey.WEBFLOW]: WebflowInstructions,
    [SDKKey.IOS]: iOSInstructions,
    [SDKKey.ANDROID]: AndroidInstructions,
    [SDKKey.REACT_NATIVE]: RNInstructions,
}

export function AdvertiseMobileReplay({
    context,
    sdkKey,
}: {
    context: 'product-analytics-onboarding' | 'flags-onboarding'
    sdkKey: SDKKey
}): JSX.Element {
    let platform = 'Mobile'
    switch (sdkKey) {
        case SDKKey.ANDROID:
            platform = 'Android'
            break
        case SDKKey.IOS:
            platform = 'iOS'
            break
        case SDKKey.REACT_NATIVE:
            platform = 'React-Native'
            break
        case SDKKey.FLUTTER:
            platform = 'Flutter'
            break
    }

    return (
        <div>
            <LemonDivider className="my-8" />
            <LemonBanner type="info">
                <h3>
                    Session Replay for {platform} <LemonTag type="highlight">NEW</LemonTag>
                </h3>
                <div>
                    Session replay is now in beta for {platform}.{' '}
                    <Link
                        to={urls.onboarding('session_replay', OnboardingStepKey.INSTALL, sdkKey)}
                        data-attr={`${context}-${platform.toLowerCase()}-replay-cta`}
                    >
                        Learn how to set it up
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}

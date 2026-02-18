import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    FlutterInstallation,
    FramerInstallation,
    HTMLSnippetInstallation,
    IOSInstallation,
    JSWebInstallation,
    NextJSInstallation,
    NuxtInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    SessionReplayFinalSteps,
    SvelteInstallation,
    VueInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/session-replay'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { OnboardingStepKey, SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const SNIPPETS = {
    SessionReplayFinalSteps,
}

// JS Web SDKs
const SessionReplayJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: SNIPPETS,
})
const SessionReplayHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HTMLSnippetInstallation,
    snippets: SNIPPETS,
})

// Frontend frameworks
const SessionReplayReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: SNIPPETS,
})
const SessionReplayNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: SNIPPETS,
})
const SessionReplaySvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: SNIPPETS,
})
const SessionReplayAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: SNIPPETS,
})
const SessionReplayAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: SNIPPETS,
})
const SessionReplayVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: SNIPPETS,
})
const SessionReplayNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: SNIPPETS,
})
const SessionReplayRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: SNIPPETS,
})

// Website builders
const SessionReplayBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: SNIPPETS,
})
const SessionReplayFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: SNIPPETS,
})
const SessionReplayWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: SNIPPETS,
})

// Mobile SDKs
const SessionReplayAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    snippets: SNIPPETS,
})
const SessionReplayIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    snippets: SNIPPETS,
})
const SessionReplayFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    snippets: SNIPPETS,
})
const SessionReplayRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    snippets: SNIPPETS,
})

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: SessionReplayJSWebInstructionsWrapper,
    [SDKKey.HTML_SNIPPET]: SessionReplayHTMLSnippetInstructionsWrapper,
    [SDKKey.ANGULAR]: SessionReplayAngularInstructionsWrapper,
    [SDKKey.ASTRO]: SessionReplayAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: SessionReplayBubbleInstructionsWrapper,
    [SDKKey.FRAMER]: SessionReplayFramerInstructionsWrapper,
    [SDKKey.NEXT_JS]: SessionReplayNextJSInstructionsWrapper,
    [SDKKey.NUXT_JS]: SessionReplayNuxtJSInstructionsWrapper,
    [SDKKey.REACT]: SessionReplayReactInstructionsWrapper,
    [SDKKey.REMIX]: SessionReplayRemixJSInstructionsWrapper,
    [SDKKey.TANSTACK_START]: SessionReplayReactInstructionsWrapper,
    [SDKKey.SVELTE]: SessionReplaySvelteInstructionsWrapper,
    [SDKKey.VITE]: SessionReplayReactInstructionsWrapper,
    [SDKKey.VUE_JS]: SessionReplayVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: SessionReplayWebflowInstructionsWrapper,
    [SDKKey.IOS]: SessionReplayIOSInstructionsWrapper,
    [SDKKey.ANDROID]: SessionReplayAndroidInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: SessionReplayRNInstructionsWrapper,
    [SDKKey.FLUTTER]: SessionReplayFlutterInstructionsWrapper,
}

export type AdvertiseMobileReplayContext =
    | 'product-analytics-onboarding'
    | 'flags-onboarding'
    | 'experiments-onboarding'

export function AdvertiseMobileReplay({
    context,
    sdkKey,
}: {
    context: AdvertiseMobileReplayContext
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
                    Session replay is now in general availability for {platform}.{' '}
                    <Link
                        to={urls.onboarding({
                            productKey: 'session_replay',
                            stepKey: OnboardingStepKey.INSTALL,
                            sdk: sdkKey,
                        })}
                        data-attr={`${context}-${platform.toLowerCase()}-replay-cta`}
                    >
                        Learn how to set it up
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}

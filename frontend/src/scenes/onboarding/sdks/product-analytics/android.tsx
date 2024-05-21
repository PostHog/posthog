import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingStepKey } from 'scenes/onboarding/onboardingLogic'
import { urls } from 'scenes/urls'

import { SDKKey } from '~/types'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function AndroidCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Kotlin}>{`PostHog.capture(event = "test-event")`}</CodeSnippet>
}

export function AdvertiseAndroidReplay({
    context,
}: {
    context: 'product-analytics-onboarding' | 'flags-onboarding'
}): JSX.Element {
    return (
        <div>
            <LemonDivider className="my-8" />
            <LemonBanner type="info">
                <h3>
                    Session Replay for Android <LemonTag type="highlight">NEW</LemonTag>
                </h3>
                <div>
                    Session replay is now in beta for Android.{' '}
                    <Link
                        to={urls.onboarding('session_replay', OnboardingStepKey.INSTALL, SDKKey.ANDROID)}
                        data-attr={`${context}-android-replay-cta`}
                    >
                        Learn how to set it up
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <h3>Send an Event</h3>
            <AndroidCaptureSnippet />
            <PersonModeEventPropertyInstructions />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseAndroidReplay context="product-analytics-onboarding" />
            </FlaggedFeature>
        </>
    )
}

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingStepKey } from 'scenes/onboarding/onboardingLogic'
import { urls } from 'scenes/urls'

import { SDKKey } from '~/types'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'

function AndroidCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Kotlin}>{`PostHog.capture(event = "test-event")`}</CodeSnippet>
}

function AdvertiseAndroidReplay(): JSX.Element {
    return (
        <div>
            <h3 className="mt-8">
                Session Replay for Android <LemonTag type="highlight">NEW</LemonTag>
            </h3>
            <div>
                Session replay is now in beta for Android.{' '}
                <Link to={urls.onboarding('session_replay', OnboardingStepKey.INSTALL, SDKKey.ANDROID)}>
                    Learn how to set it up
                </Link>
            </div>
        </div>
    )
}

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <h3>Send an Event</h3>
            <AndroidCaptureSnippet />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseAndroidReplay />
            </FlaggedFeature>
        </>
    )
}

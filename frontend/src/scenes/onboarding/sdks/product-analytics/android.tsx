import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

import { SDKKey } from '~/types'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function AndroidCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Kotlin}>{`PostHog.capture(event = "test-event")`}</CodeSnippet>
}

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <h3>Send an Event</h3>
            <AndroidCaptureSnippet />
            <PersonModeEventPropertyInstructions />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.ANDROID} />
            </FlaggedFeature>
        </>
    )
}

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function IOSCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Swift}>{`PostHogSDK.shared.capture("Test Event")`}</CodeSnippet>
}

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <h3>Send an event</h3>
            <IOSCaptureSnippet />
            <PersonModeEventPropertyInstructions />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.IOS} />
            </FlaggedFeature>
        </>
    )
}

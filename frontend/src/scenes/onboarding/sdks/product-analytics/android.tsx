import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

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
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.ANDROID} />
        </>
    )
}

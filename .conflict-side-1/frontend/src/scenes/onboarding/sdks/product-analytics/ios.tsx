import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

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
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.IOS} />
        </>
    )
}

import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function RNInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {'yarn add posthog-react-native\n\nyarn react-native link\n\n# for iOS\ncd ios\npod install'}
        </CodeSnippet>
    )
}

function RNSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = window.location.origin
    return (
        <CodeSnippet language={Language.JSX}>
            {"import PostHog from 'posthog-react-native'\n\nawait PostHog.setup('" +
                currentTeam?.api_token +
                "', {\n\t// PostHog API host\n\thost: '" +
                url +
                "',\n\n\t// Record certain application events automatically! (off/false by default)\n\tcaptureApplicationLifecycleEvents: true,\n\n\t// Capture deep links as part of the screen call. (off by default)\n\tcaptureDeepLinks: true,\n\n\t// Record screen views automatically! (off/false by default)\n\trecordScreenViews: true,\n\n\t// Max delay before flushing the queue (30 seconds)\n\tflushInterval: 30,\n\n\t// Maximum number of events to keep in queue before flushing (20)\n\tflushAt: 20,\n\n\t// Used only for Android\n\tandroid: {\n\t\t// Enable or disable collection of ANDROID_ID (true)\n\t\tcollectDeviceId: true,\n\t},\n\n\t// Used only for iOS\n\tiOS: {\n\t\t// Automatically capture in-app purchases from the App Store\n\t\tcaptureInAppPurchases: false,\n\n\t\t// Capture push notifications\n\t\tcapturePushNotifications: false,\n\n\t\t// Capture advertisting info\n\t\tenableAdvertisingCapturing: true,\n\n\t\t// The maximum number of items to queue before starting to drop old ones.\n\t\tmaxQueueSize: 1000,\n\n\t\t// Record bluetooth information.\n\t\tshouldUseBluetooth: false,\n\n\t\t// Use location services. Will ask for permissions.\n\t\tshouldUseLocationServices: false\n\t}\n})"}
        </CodeSnippet>
    )
}

function RNCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.JSX}>{"PostHog.capture('test-event')"}</CodeSnippet>
}

export function RNInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <RNInstallSnippet />
            <h3>Configure</h3>
            <RNSetupSnippet />
            <h3>Send an Event</h3>
            <RNCaptureSnippet />
        </>
    )
}

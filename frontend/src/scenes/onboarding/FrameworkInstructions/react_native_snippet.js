import React from 'react'
import Snippet from './snippet'

function RNInstallSnippet() {
    return (
        <Snippet>
            <span>{'yarn add posthog-react-native\n\nyarn react-native link\n\n//For IOS\ncd ios\npod install'}</span>
        </Snippet>
    )
}

function RNSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {"import PostHog from 'posthog-react-native'\n\nawait PostHog.setup('" +
                    user.team.api_token +
                    "', {\n\t// PostHog API host\n\thost: '" +
                    url +
                    "',\n\n\t// Record certain application events automatically! (off/false by default)\n\tcaptureApplicationLifecycleEvents: true,\n\n\t// Capture deep links as part of the screen call. (off by default)\n\tcaptureDeepLinks: true,\n\n\t// Record screen views automatically! (off/false by default)\n\trecordScreenViews: true,\n\n\t// Max delay before flushing the queue (30 seconds)\n\tflushInterval: 30,\n\n\t// Maximum number of events to keep in queue before flushing (20)\n\tflushAt: 20,\n\n\t// Used only for Android\n\tandroid: {\n\t\t// Enable or disable collection of ANDROID_ID (true)\n\t\tcollectDeviceId: true,\n\t},\n\n\t// Used only for iOS\n\tiOS: {\n\t\t// Automatically capture in-app purchases from the App Store\n\t\tcaptureInAppPurchases: false,\n\n\t\t// Capture push notifications\n\t\tcapturePushNotifications: false,\n\n\t\t// Capture advertisting info\n\t\tenableAdvertisingCapturing: true,\n\n\t\t// The maximum number of items to queue before starting to drop old ones.\n\t\tmaxQueueSize: 1000,\n\n\t\t// Record bluetooth information.\n\t\tshouldUseBluetooth: false,\n\n\t\t// Use location services. Will ask for permissions.\n\t\tshouldUseLocationServices: false\n\t}\n})"}
            </span>
        </Snippet>
    )
}

function RNCaptureSnippet() {
    return (
        <Snippet>
            <span>{"PostHog.capture('test-event')"}</span>
        </Snippet>
    )
}

export function RNInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <RNInstallSnippet></RNInstallSnippet>
            <h3>Configure</h3>
            <RNSetupSnippet user={user}></RNSetupSnippet>
            <h3>Send an Event</h3>
            <RNCaptureSnippet></RNCaptureSnippet>
        </>
    )
}

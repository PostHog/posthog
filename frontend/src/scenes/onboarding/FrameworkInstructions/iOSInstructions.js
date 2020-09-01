import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function IOSInstallSnippet() {
    return (
        <CodeSnippet language="ruby">
            {'pod "PostHog", "~> 1.0" # Cocoapods \n# OR \ngithub "posthog/posthog-ios" # Carthage'}
        </CodeSnippet>
    )
}

function IOS_OBJ_C_SetupSnippet({ user }) {
    return (
        <CodeSnippet language="objectivec">
            {`#import <PostHog/PHGPostHog.h>\n#import <PostHog/PHGPostHogConfiguration.h>\n\nPHGPostHogConfiguration *configuration = [PHGPostHogConfiguration configurationWithApiKey:@"${user.team.api_token}" host:@"${window.location.origin}"];\n\nconfiguration.captureApplicationLifecycleEvents = YES; // Record certain application events automatically!\nconfiguration.recordScreenViews = YES; // Record screen views automatically!\n\n[PHGPostHog setupWithConfiguration:configuration];`}
        </CodeSnippet>
    )
}

function IOS_SWIFT_SetupSnippet({ user }) {
    return (
        <CodeSnippet language="swift">
            {`import PostHog\n\nlet configuration = PHGPostHogConfiguration(apiKey: "${user.team.api_token}", host: "${window.location.origin}")\n\nconfiguration.captureApplicationLifecycleEvents = true; // Record certain application events automatically!\nconfiguration.recordScreenViews = true; // Record screen views automatically!\n\nPHGPostHog.setup(with: configuration)\nlet posthog = PHGPostHog.shared()`}
        </CodeSnippet>
    )
}

function IOS_OBJ_C_CaptureSnippet() {
    return <CodeSnippet language="objectivec">{'[[PHGPostHog sharedPostHog] capture:@"Test Event"];'}</CodeSnippet>
}

function IOS_SWIFT_CaptureSnippet() {
    return <CodeSnippet language="swift">{'posthog.capture("Test Event")'}</CodeSnippet>
}

export function IOSInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <IOSInstallSnippet></IOSInstallSnippet>
            <h3>Configure Swift</h3>
            <IOS_SWIFT_SetupSnippet user={user}></IOS_SWIFT_SetupSnippet>
            <h3>Or Configure Objective-C</h3>
            <IOS_OBJ_C_SetupSnippet user={user}></IOS_OBJ_C_SetupSnippet>
            <h2>Send an Event</h2>
            <h3>Swift</h3>
            <IOS_SWIFT_CaptureSnippet></IOS_SWIFT_CaptureSnippet>
            <h3>Objective-C</h3>
            <IOS_OBJ_C_CaptureSnippet></IOS_OBJ_C_CaptureSnippet>
        </>
    )
}

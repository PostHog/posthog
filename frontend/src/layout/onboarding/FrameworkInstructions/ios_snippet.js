import React from 'react'
import Snippet from './snippet'

function IOSInstallSnippet() {
    return (
        <Snippet>
            <span>{'pod "PostHog", "~> 1.0" // Coacoapods \n// or \ngithub "posthog/posthog-ios" // carthage'}</span>
        </Snippet>
    )
}

function IOS_OBJ_C_SetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'#import <PostHog/PHGPostHog.h>\n#import <PostHog/PHGPostHogConfiguration.h>\n\nPHGPostHogConfiguration *configuration = [PHGPostHogConfiguration configurationWithApiKey:@"' +
                    user.team.api_token +
                    '" host:@"' +
                    url +
                    '"];\n\nconfiguration.captureApplicationLifecycleEvents = YES; // Record certain application events automatically!\nconfiguration.recordScreenViews = YES; // Record screen views automatically!\n\n[PHGPostHog setupWithConfiguration:configuration];'}
            </span>
        </Snippet>
    )
}

function IOS_SWIFT_SetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'import PostHog\n\nlet configuration = PHGPostHogConfiguration(apiKey: "' +
                    user.team.api_token +
                    '", host: "' +
                    url +
                    '")\n\nconfiguration.captureApplicationLifecycleEvents = true; // Record certain application events automatically!\nconfiguration.recordScreenViews = true; // Record screen views automatically!\n\nPHGPostHog.setup(with: configuration)\nlet posthog = PHGPostHog.shared()'}
            </span>
        </Snippet>
    )
}

function IOS_OBJ_C_CaptureSnippet() {
    return (
        <Snippet>
            <span>{'[[PHGPostHog sharedPostHog] capture:@"Test Event"];'}</span>
        </Snippet>
    )
}

function IOS_SWIFT_CaptureSnippet() {
    return (
        <Snippet>
            <span>{'posthog.capture("Test Event")'}</span>
        </Snippet>
    )
}

export function IOSInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <IOSInstallSnippet></IOSInstallSnippet>
            <h3>Configure Swift</h3>
            <IOS_SWIFT_SetupSnippet user={user}></IOS_SWIFT_SetupSnippet>
            <h3>Or Configure Obj-C</h3>
            <IOS_OBJ_C_SetupSnippet user={user}></IOS_OBJ_C_SetupSnippet>
            <h2>Send an Event</h2>
            <h3>Swift</h3>
            <IOS_SWIFT_CaptureSnippet></IOS_SWIFT_CaptureSnippet>
            <h3>Obj-C</h3>
            <IOS_OBJ_C_CaptureSnippet></IOS_OBJ_C_CaptureSnippet>
        </>
    )
}

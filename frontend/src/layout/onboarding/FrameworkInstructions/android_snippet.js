import React from 'react'
import Snippet from './snippet'

function AndroidInstallSnippet() {
    return (
        <Snippet>
            <span>{"dependencies {\n\timplementation 'com.posthog.android:posthog:1.+'\n}"}</span>
        </Snippet>
    )
}

function AndroidSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'public class SampleApp extends Application {\n\tprivate static final String POSTHOG_API_KEY = "' +
                    user.team.api_token +
                    '";\n\tprivate static final String POSTHOG_HOST = "' +
                    url +
                    '";\n\n\t@Override\n\tpublic void onCreate() {\n\t\t// Create a PostHog client with the given context, API key and host.\n\t\tPostHog posthog = new PostHog.Builder(this, POSTHOG_API_KEY, POSTHOG_HOST)\n\t\t\t.captureApplicationLifecycleEvents() // Record certain application events automatically!\n\t\t\t.recordScreenViews() // Record screen views automatically!\n\t\t\t.build();\n\n\t\t// Set the initialized instance as a globally accessible instance.\n\t\tPostHog.setSingletonInstance(posthog);\n\n\t\t// Now anytime you call PostHog.with, the custom instance will be returned.\n\t\tPostHog posthog = PostHog.with(this);\n\t}\n}'}
            </span>
        </Snippet>
    )
}

function AndroidCaptureSnippet() {
    return (
        <Snippet>
            <span>{'PostHog.with(this).capture("test-event");'}</span>
        </Snippet>
    )
}

export function AndroidInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <AndroidInstallSnippet></AndroidInstallSnippet>
            <h3>Configure</h3>
            <AndroidSetupSnippet user={user}></AndroidSetupSnippet>
            <h3>Send an Event</h3>
            <AndroidCaptureSnippet></AndroidCaptureSnippet>
        </>
    )
}

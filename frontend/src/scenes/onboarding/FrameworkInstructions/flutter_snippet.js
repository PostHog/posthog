import React from 'react'
import Snippet from './snippet'
import '../onboardingWizard.scss'

function FlutterInstallSnippet() {
    return (
        <Snippet>
            <span>{'posthog_flutter: #insert version number'}</span>
        </Snippet>
    )
}

function FlutterCaptureSnippet() {
    return (
        <Snippet>
            <span>
                {
                    "import 'package:posthog_flutter/posthog_flutter.dart';\n\n...\nPosthog.screen(\n\tscreenName: 'Example Screen',\n);"
                }
            </span>
        </Snippet>
    )
}

function FlutterAndroidSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.API_KEY" android:value="' +
                    user.team.api_token +
                    '" />\n\t<meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="' +
                    url +
                    '" />\n\t<meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="false" />\n\tmeta-data android:name="com.posthog.posthog.DEBUG" android:value="false" />\n</application>;'}
            </span>
        </Snippet>
    )
}

function FlutterIOSSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>
                {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.API_KEY</key>\n\t<string>' +
                    user.team.api_token +
                    '</string>\n\t<key>com.posthog.posthog.POSTHOG_HOST</key>\n\t<string>' +
                    url +
                    '</string>\n\t<key>com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS</key>\n\t<false/>\n\t<false/>\n\t[...]\n</dict>'}
            </span>
        </Snippet>
    )
}

export function FlutterInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <FlutterInstallSnippet></FlutterInstallSnippet>
            <h3>Android Setup</h3>
            <p className="prompt-text">{'Add these values in AndroidManifest.xml'}</p>
            <FlutterAndroidSetupSnippet user={user}></FlutterAndroidSetupSnippet>
            <h3>IOS Setup</h3>
            <p className="prompt-text">{'Add these values in Info.plist'}</p>
            <FlutterIOSSetupSnippet user={user}></FlutterIOSSetupSnippet>
            <h3>Send an Event</h3>
            <FlutterCaptureSnippet></FlutterCaptureSnippet>
        </>
    )
}

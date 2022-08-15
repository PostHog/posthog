import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function FlutterInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.YAML}>{'posthog_flutter: # insert version number'}</CodeSnippet>
}

function FlutterCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Dart}>
            {
                "import 'package:posthog_flutter/posthog_flutter.dart';\n\nPosthog.screen(\n\tscreenName: 'Example Screen',\n);"
            }
        </CodeSnippet>
    )
}

function FlutterAndroidSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = window.location.origin

    return (
        <CodeSnippet language={Language.XML}>
            {'<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.API_KEY" android:value="' +
                currentTeam?.api_token +
                '" />\n\t<meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="' +
                url +
                '" />\n\t<meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="false" />\n\t<meta-data android:name="com.posthog.posthog.DEBUG" android:value="false" />\n</application>'}
        </CodeSnippet>
    )
}

function FlutterIOSSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = window.location.origin

    return (
        <CodeSnippet language={Language.XML}>
            {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.API_KEY</key>\n\t<string>' +
                currentTeam?.api_token +
                '</string>\n\t<key>com.posthog.posthog.POSTHOG_HOST</key>\n\t<string>' +
                url +
                '</string>\n\t<key>com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS</key>\n\t<false/>\n\t<false/>\n\t[...]\n</dict>'}
        </CodeSnippet>
    )
}

export function FlutterInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <FlutterInstallSnippet />
            <h3>Android Setup</h3>
            <p className="prompt-text">{'Add these values in AndroidManifest.xml'}</p>
            <FlutterAndroidSetupSnippet />
            <h3>iOS Setup</h3>
            <p className="prompt-text">{'Add these values in Info.plist'}</p>
            <FlutterIOSSetupSnippet />
            <h3>Send an Event</h3>
            <FlutterCaptureSnippet />
        </>
    )
}

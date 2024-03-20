import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'

function FlutterCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Dart}>
            {
                "import 'package:posthog_flutter/posthog_flutter.dart';\n\nawait Posthog().screen(\n\tscreenName: 'Example Screen',\n);"
            }
        </CodeSnippet>
    )
}

export function ProductAnalyticsFlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions />
            <h3>Send an Event</h3>
            <FlutterCaptureSnippet />
        </>
    )
}

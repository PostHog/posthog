import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKKey } from '~/types'

import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'
import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

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
            <PersonModeEventPropertyInstructions />
            <AdvertiseMobileReplay context="product-analytics-onboarding" sdkKey={SDKKey.FLUTTER} />
        </>
    )
}

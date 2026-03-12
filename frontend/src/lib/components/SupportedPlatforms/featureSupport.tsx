import { Link } from '@posthog/lemon-ui'

import { Feature, PlatformSupportConfig } from './types'

export const FEATURE_SUPPORT: Record<Feature, PlatformSupportConfig> = {
    errorTrackingExceptionAutocapture: {
        web: { version: '1.207.8', note: 'Not supported by the js-lite package' },
        android: {
            version: '3.24.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/error-tracking/installation/android#set-up-exception-autocapture">
                        Exception autocapture is supported on Android
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 3.32.0 or higher.
                </>
            ),
        },
        flutter: {
            note: (
                <>
                    <Link to="https://posthog.com/docs/error-tracking/installation/flutter#set-up-exception-autocapture">
                        Exception autocapture is supported on Flutter
                    </Link>{' '}
                    but is not controlled remotely by this toggle
                </>
            ),
        },
        reactNative: {
            version: '4.14.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/error-tracking/installation/react-native#set-up-exception-autocapture">
                        Exception autocapture is supported on React Native
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 4.35.0 or higher.
                </>
            ),
        },
    },
    errorTrackingSuppressionRules: {
        web: { version: '1.249.4' },
    },
    sessionReplayLogCapture: {
        android: {
            version: '3.4.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/console-log-recording?tab=Android">
                        Console log recording is supported on Android
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 3.32.0 or higher.
                </>
            ),
        },
        ios: {
            version: '3.26.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/console-log-recording?tab=iOS">
                        Console log recording is supported on iOS
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 3.41.1 or higher.
                </>
            ),
        },
        web: { version: '1.18.0' },
        reactNative: {
            version: '3.9.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/console-log-recording?tab=React+Native">
                        Console log recording is supported on Android only
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 4.35.0 or higher.
                </>
            ),
        },
    },
    sessionReplayCanvasCapture: {
        flutter: {
            version: '4.7.0',
            note: (
                <>
                    If you're using the <code>canvaskit</code> renderer on Flutter Web, you must also enable canvas
                    capture
                </>
            ),
        },
        web: { version: '1.101.0' },
    },
    sessionReplayCaptureRequests: {
        android: {
            version: '3.4.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/network-recording?tab=Android">
                        Network recording is supported on Android
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 3.32.0 or higher.
                </>
            ),
        },
        ios: {
            version: '3.12.6',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/network-recording?tab=iOS">
                        Network recording is supported on iOS
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 3.41.1 or higher.
                </>
            ),
        },
        web: { version: '1.39.0' },
        reactNative: {
            version: '3.2.0',
            note: (
                <>
                    <Link to="https://posthog.com/docs/session-replay/network-recording?tab=React+Native">
                        Network recording is supported on iOS only
                    </Link>{' '}
                    and can be controlled remotely using this toggle when running SDK version 4.35.0 or higher.
                </>
            ),
        },
    },
    sessionReplayCaptureHeadersAndPayloads: {
        web: { version: '1.104.4' },
    },
    sessionReplayAuthorizedDomains: {
        web: { version: '1.5.0' },
    },
    sessionReplayMasking: {
        web: { version: '1.227.0' },
    },
    autocapture: {
        web: { version: '1.0.0' },
        reactNative: { note: 'via code config' },
        ios: { note: 'via code config' },
    },
    heatmaps: {
        web: { version: '1.102.0' },
    },
    deadClicks: {
        web: { version: '1.165.0' },
    },
    webVitals: {
        web: { version: '1.141.2' },
    },
    surveys: {
        web: { version: '1.81.1' },
        android: { note: 'via API' },
        ios: { version: '3.31.0' },
        reactNative: { version: '3.12.0' },
    },
    logsCapture: {
        web: { version: '1.329.0' },
    },
}

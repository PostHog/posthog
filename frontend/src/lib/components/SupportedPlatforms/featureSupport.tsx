import { Link } from '@posthog/lemon-ui'

import { Feature, PlatformSupportConfig } from './types'

export const FEATURE_SUPPORT: Record<Feature, PlatformSupportConfig> = {
    errorTrackingExceptionAutocapture: {
        web: { version: '1.207.8', note: 'Not supported by the js-lite package' },
        android: {
            note: (
                <>
                    <Link to="https://posthog.com/docs/error-tracking/installation/android#set-up-exception-autocapture">
                        Exception autocapture is supported on Android
                    </Link>{' '}
                    but is not controlled remotely by this toggle
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
            note: (
                <>
                    <Link to="https://posthog.com/docs/error-tracking/installation/react-native#set-up-exception-autocapture">
                        Exception autocapture is supported on React Native
                    </Link>{' '}
                    but is not controlled remotely by this toggle
                </>
            ),
        },
    },
    errorTrackingSuppressionRules: {
        web: { version: '1.249.4' },
    },
    sessionReplayLogCapture: {
        android: { version: '1.0.0' },
        ios: { version: '3.26.0' },
        web: { version: '1.18.0' },
        reactNative: {
            version: '3.9.0',
            note: <>Android only</>,
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
        android: { version: '3.1.0' },
        ios: { version: '3.12.6' },
        web: { version: '1.39.0' },
        reactNative: { note: <>RN network capture is only supported on iOS</> },
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
}

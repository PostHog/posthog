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
}

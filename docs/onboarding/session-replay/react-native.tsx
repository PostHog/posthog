import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        {
            title: 'Install the packages',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the PostHog React Native library, its dependencies, and the session replay plugin:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Expo',
                                code: dedent`
                                    npx expo install posthog-react-native expo-file-system expo-application expo-device expo-localization posthog-react-native-session-replay
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-react-native @react-native-async-storage/async-storage react-native-device-info react-native-localize posthog-react-native-session-replay

                                    # for iOS
                                    cd ios && pod install
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm i -s posthog-react-native @react-native-async-storage/async-storage react-native-device-info react-native-localize posthog-react-native-session-replay

                                    # for iOS
                                    cd ios && pod install
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="SDK version">
                        <Markdown>
                            Session replay requires PostHog React Native SDK version 3.2.0 or higher. We recommend
                            always using the latest version.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Enable session recordings in project settings',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your PostHog [Project Settings](https://us.posthog.com/settings/project-replay) and enable
                        **Record user sessions**. Session recordings will not work without this setting enabled.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog with session replay',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add `enableSessionReplay: true` to your PostHog configuration. Here are all the available
                        options:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'App.tsx',
                                code: dedent`
                                    import { PostHogProvider } from 'posthog-react-native'

                                    export function MyApp() {
                                        return (
                                            <PostHogProvider
                                                apiKey="<ph_project_api_key>"
                                                options={{
                                                    host: "<ph_client_api_host>",

                                                    // Enable session recording. Requires enabling in your project settings as well.
                                                    // Default is false.
                                                    enableSessionReplay: true,

                                                    sessionReplayConfig: {
                                                        // Whether text inputs are masked. Default is true.
                                                        // Password inputs are always masked regardless
                                                        maskAllTextInputs: true,

                                                        // Whether images are masked. Default is true.
                                                        maskAllImages: true,

                                                        // Capture logs automatically. Default is true.
                                                        // Android only (Native Logcat only)
                                                        captureLog: true,

                                                        // Whether network requests are captured in recordings. Default is true
                                                        // Only metric-like data like speed, size, and response code are captured.
                                                        // No data is captured from the request or response body.
                                                        // iOS only
                                                        captureNetworkTelemetry: true,

                                                        // Throttling delay used to reduce the number of snapshots captured
                                                        // and reduce performance impact. Default is 1000ms
                                                        throttleDelayMs: 1000,
                                                    },
                                                }}
                                            >
                                                <RestOfApp />
                                            </PostHogProvider>
                                        )
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        For more configuration options, see the [React Native session replay
                        docs](https://posthog.com/docs/session-replay/installation?tab=React+Native).
                    </Markdown>
                    <CalloutBox type="fyi" title="Requirements">
                        <Markdown>
                            Requires Android API 26+ and iOS 13+. Expo Go is not supported - use a development build.
                            Session replay is only supported on Android and iOS platforms.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)

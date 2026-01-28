import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog React Native library and its dependencies:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Expo',
                                code: dedent`
                                    npx expo install posthog-react-native expo-file-system expo-application expo-device expo-localization
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-react-native @react-native-async-storage/async-storage react-native-device-info react-native-localize

                                    # for iOS
                                    cd ios && pod install
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm i -s posthog-react-native @react-native-async-storage/async-storage react-native-device-info react-native-localize

                                    # for iOS
                                    cd ios && pod install
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        PostHog is most easily used via the `PostHogProvider` component. Wrap your app with the
                        provider:
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
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events using the `usePostHog` hook:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'Component.tsx',
                                code: dedent`
                                    import { usePostHog } from 'posthog-react-native'

                                    function MyComponent() {
                                        const posthog = usePostHog()

                                        const handlePress = () => {
                                            posthog.capture('button_pressed', {
                                                button_name: 'signup'
                                            })
                                        }

                                        return <Button onPress={handlePress} title="Sign Up" />
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)

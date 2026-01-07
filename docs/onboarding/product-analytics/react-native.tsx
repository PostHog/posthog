import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ReactNativeInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the package" badge="required">
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
            </Step>

            <Step title="Configure PostHog" badge="required">
                <Markdown>
                    PostHog is most easily used via the `PostHogProvider` component. Wrap your app with the provider:
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
            </Step>

            <Step title="Send events">
                <Markdown>Capture custom events using the `usePostHog` hook:</Markdown>
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
            </Step>
        </Steps>
    )
}

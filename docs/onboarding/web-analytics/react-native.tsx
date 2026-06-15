import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactNativeSteps as getReactNativeStepsPA } from '../product-analytics/react-native'
import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getReactNativeStepsPA(ctx)

    // Replace the "Send events" step with web analytics specific content
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'Send events') {
            return {
                title: 'Track screen views',
                badge: 'recommended' as const,
                content: (
                    <>
                        {MobileFinalSteps && <MobileFinalSteps />}
                        <Markdown>
                            To automatically capture screen views with React Navigation, use the `usePostHogCapture`
                            hook:
                        </Markdown>
                        <CodeBlock
                            blocks={[
                                {
                                    language: 'tsx',
                                    file: 'App.tsx',
                                    code: dedent`
                                        import { usePostHogCapture } from 'posthog-react-native'
                                        import { NavigationContainer } from '@react-navigation/native'

                                        function App() {
                                            const routeNameRef = useRef<string>()
                                            const navigationRef = useRef<NavigationContainerRef<any>>()
                                            const captureEvent = usePostHogCapture()

                                            return (
                                                <NavigationContainer
                                                    ref={navigationRef}
                                                    onReady={() => {
                                                        routeNameRef.current = navigationRef.current?.getCurrentRoute()?.name
                                                    }}
                                                    onStateChange={async () => {
                                                        const previousRouteName = routeNameRef.current
                                                        const currentRouteName = navigationRef.current?.getCurrentRoute()?.name

                                                        if (previousRouteName !== currentRouteName) {
                                                            captureEvent('$screen', { $screen_name: currentRouteName })
                                                        }
                                                        routeNameRef.current = currentRouteName
                                                    }}
                                                >
                                                    {/* App content */}
                                                </NavigationContainer>
                                            )
                                        }
                                    `,
                                },
                            ]}
                        />
                    </>
                ),
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)

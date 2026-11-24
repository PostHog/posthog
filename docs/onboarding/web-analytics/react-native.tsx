import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getReactNativeInstallSteps } from '../product-analytics/react-native'
import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    return [
        ...getReactNativeInstallSteps(ctx),
        {
            title: 'Track screen views',
            badge: 'recommended' as const,
            content: (
                <>
                    {MobileFinalSteps && <MobileFinalSteps />}
                    <Markdown>
                        {dedent`
                            To capture screen views with React Navigation, set \`autocapture={{ captureScreens: false }}\` on
                            \`PostHogProvider\` and call \`posthog.screen()\` when the route changes. Get the client with the
                            \`usePostHog\` hook, and render this component inside \`PostHogProvider\`:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'App.tsx',
                                code: dedent`
                                    import { useRef } from 'react'
                                    import { usePostHog } from 'posthog-react-native'
                                    import { NavigationContainer, type NavigationContainerRef } from '@react-navigation/native'

                                    function App() {
                                        const routeNameRef = useRef<string | undefined>(undefined)
                                        const navigationRef = useRef<NavigationContainerRef<any>>(null)
                                        const posthog = usePostHog()

                                        return (
                                            <NavigationContainer
                                                ref={navigationRef}
                                                onReady={() => {
                                                    const initialRouteName = navigationRef.current?.getCurrentRoute()?.name
                                                    if (initialRouteName) {
                                                        posthog.screen(initialRouteName)
                                                    }
                                                    routeNameRef.current = initialRouteName
                                                }}
                                                onStateChange={async () => {
                                                    const previousRouteName = routeNameRef.current
                                                    const currentRouteName = navigationRef.current?.getCurrentRoute()?.name

                                                    if (previousRouteName !== currentRouteName) {
                                                        if (currentRouteName) {
                                                            posthog.screen(currentRouteName)
                                                        }
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
        },
    ]
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)

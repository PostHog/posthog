import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactNativeSteps as getReactNativeStepsPA } from '../product-analytics/react-native'
import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    // Get installation steps from product-analytics
    const installationSteps = getReactNativeStepsPA(ctx)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Use feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            PostHog provides hooks to make it easy to use feature flags in your React Native app. Use \`useFeatureFlagResult\` to get the full flag result:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'Component.tsx',
                                code: dedent`
                                    import { useFeatureFlagResult } from 'posthog-react-native'

                                    function MyComponent() {
                                        const result = useFeatureFlagResult('flag-key')
                                        if (result?.enabled) {
                                            // Do something differently for this user
                                            // Optional: use the flag payload
                                            const matchedFlagPayload = result.payload
                                        }

                                        return <View>...</View>
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            ### Multivariate flags

                            For multivariate flags, check the \`variant\` property:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'Component.tsx',
                                code: dedent`
                                    import { useFeatureFlagResult } from 'posthog-react-native'

                                    function MyComponent() {
                                        const result = useFeatureFlagResult('flag-key')
                                        if (result?.variant === 'variant-key') { // replace 'variant-key' with the key of your variant
                                            // Do something differently for this user
                                        }

                                        return <View>...</View>
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an experiment by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...flagSteps]
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)

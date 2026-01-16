import { getReactNativeSteps as getReactNativeStepsPA } from '../product-analytics/react-native'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getReactNativeSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
    // Get installation steps from product-analytics
    const installationSteps = getReactNativeStepsPA(CodeBlock, Markdown, dedent)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Use feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            PostHog provides hooks to make it easy to use feature flags in your React Native app. Use \`useFeatureFlagEnabled\` for boolean flags:
                        `}
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
                                        const isMyFlagEnabled = posthog.isFeatureEnabled('flag-key')

                                        if (isMyFlagEnabled) {
                                            // Do something differently for this user
                                            // Optional: fetch the payload
                                            const matchedFlagPayload = posthog.getFeatureFlagPayload('flag-key')
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

                            For multivariate flags, use \`getFeatureFlag\`:
                        `}
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
                                        const enabledVariant = posthog.getFeatureFlag('flag-key')

                                        if (enabledVariant === 'variant-key') { // replace 'variant-key' with the key of your variant
                                            // Do something differently for this user
                                            // Optional: fetch the payload
                                            const matchedFlagPayload = posthog.getFeatureFlagPayload('flag-key')
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

export const ReactNativeInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getReactNativeSteps(CodeBlock, Markdown, dedent)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}

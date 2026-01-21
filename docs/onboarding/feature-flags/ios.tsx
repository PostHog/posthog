import { getIOSSteps as getIOSStepsPA } from '../product-analytics/ios'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getIOSSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
    // Get installation steps from product-analytics
    const installationSteps = getIOSStepsPA(CodeBlock, Markdown, dedent)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Evaluate boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Swift',
                                code: dedent`
                                    let isMyFlagEnabled = PostHogSDK.shared.isFeatureEnabled("flag-key")
                                    if isMyFlagEnabled {
                                        // Do something differently for this user
                                        // Optional: fetch the payload
                                        let matchedFlagPayload = PostHogSDK.shared.getFeatureFlagPayload("flag-key")
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Evaluate multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Swift',
                                code: dedent`
                                    let enabledVariant = PostHogSDK.shared.getFeatureFlag("flag-key")
                                    if enabledVariant == "variant-key" { // replace 'variant-key' with the key of your variant
                                        // Do something differently for this user
                                        // Optional: fetch the payload
                                        let matchedFlagPayload = PostHogSDK.shared.getFeatureFlagPayload("flag-key")
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

export const IOSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getIOSSteps(CodeBlock, Markdown, dedent)

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

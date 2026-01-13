import { getBubbleSteps as getBubbleStepsPA } from '../product-analytics/bubble'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getBubbleSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getBubbleStepsPA(CodeBlock, Markdown, dedent, snippets)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Use boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    {BooleanFlag && <BooleanFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Use multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    {MultivariateFlag && <MultivariateFlag language="javascript" />}
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

    const allSteps = [...installationSteps, ...flagSteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const BubbleInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getBubbleSteps(CodeBlock, Markdown, dedent, snippets, { modifySteps })

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

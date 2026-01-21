import { getWebflowSteps as getWebflowStepsPA } from '../product-analytics/webflow'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getWebflowSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics only
    const installationSteps = getWebflowStepsPA(CodeBlock, Markdown, dedent, snippets).filter(
        (step: StepDefinition) => step.title !== 'Send events'
    )

    // Add experiments-specific steps
    const experimentSteps: StepDefinition[] = [
        {
            title: 'Implement your experiment',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Experiments run on top of our feature flags. You can define which version of your code runs based on the return value of the feature flag:
                        `}
                    </Markdown>
                    {ExperimentImplementation && <ExperimentImplementation language="javascript" />}
                </>
            ),
        },
        {
            title: 'Run your experiment',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Once you've implemented the feature flag in your code, you'll enable it for a target audience by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    const allSteps = [...installationSteps, ...experimentSteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const WebflowInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getWebflowSteps(CodeBlock, Markdown, dedent, snippets, { modifySteps })

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

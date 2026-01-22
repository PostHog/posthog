import { getPythonSteps as getPythonStepsPA } from '../product-analytics/python'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getPythonSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics only (exclude "Send events")
    const installationSteps = getPythonStepsPA(CodeBlock, Markdown, CalloutBox, dedent, snippets).filter(
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

                            **Note:** Server-side experiment metrics require you to manually send the feature flag information. See [this tutorial](https://posthog.com/docs/experiments/adding-experiment-code) for more information.
                        `}
                    </Markdown>
                    {ExperimentImplementation && <ExperimentImplementation language="python" />}
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

export const PythonInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()
    const steps = getPythonSteps(CodeBlock, Markdown, CalloutBox, dedent, snippets, { modifySteps })

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

import { getNextJSSteps as getNextJSStepsPA } from '../product-analytics/nextjs'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getNextJSSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    Tab: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {

    const installationSteps = getNextJSStepsPA(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets)

    // Add survey steps here if needed
    const surveySteps: StepDefinition[] = []

    const allSteps = [...installationSteps, ...surveySteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const NextJSInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = useMDXComponents()
    const steps = getNextJSSteps(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets, { modifySteps })

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

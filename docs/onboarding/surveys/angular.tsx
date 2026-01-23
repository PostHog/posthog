import { getAngularSteps as getAngularStepsPA } from '../product-analytics/angular'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getAngularSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    Tab: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {

    const installationSteps = getAngularStepsPA(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets).filter(
        (step: StepDefinition) => step.title !== 'Send events'
    )

    // Add survey steps here if needed
    const surveySteps: StepDefinition[] = []

    const allSteps = [...installationSteps, ...surveySteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const AngularInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = useMDXComponents()
    const steps = getAngularSteps(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets, { modifySteps })

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

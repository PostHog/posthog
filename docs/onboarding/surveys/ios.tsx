import { getIOSSteps as getIOSStepsPA } from '../product-analytics/ios'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getIOSSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    options?: StepModifier
): StepDefinition[] => {

    const installationSteps = getIOSStepsPA(CodeBlock, Markdown, dedent)

    // Add survey steps here if needed
    const surveySteps: StepDefinition[] = [
        {
            title: 'Enable surveys in your configuration',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                    To enable surveys in your iOS app, enable surveys in your PostHog configuration:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Swift',
                                code: dedent`
                                    let POSTHOG_API_KEY = "<ph_project_api_key>"
                                    let POSTHOG_HOST = "<ph_client_api_host>"

                                    // Surveys require iOS 15.0 or later
                                    if #available(iOS 15.0, *) {
                                        config.surveys = true
                                    }

                                    PostHogSDK.shared.setup(config)
                                `,
                            },
                        ]}
                    />
                </>
            )
        }
    ]

    const allSteps = [...installationSteps, ...surveySteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const iOSInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getIOSSteps(CodeBlock, Markdown, dedent, { modifySteps })

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

import { getReactNativeSteps as getReactNativeStepsPA } from '../product-analytics/react-native'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getReactNativeSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const installationSteps = getReactNativeStepsPA(CodeBlock, Markdown, dedent, snippets)

    // Add survey steps here if needed
    const surveySteps: StepDefinition[] = [
        {
            title: 'Install survey dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Next, install the dependencies for surveys. Using surveys requires PostHog's React Native SDK version **4.5.0 or higher**. We recommend always using the latest version.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add react-native-safe-area-context react-native-svg
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm i -s react-native-safe-area-context react-native-svg
                                `,
                            },
                        ]}
                    />
                </>
            )
        },
        {
            title: 'Add the surveys provider',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add PostHogSurveyProvider to your app anywhere inside PostHogProvider. This component fetches surveys. It also acts as the root for where popover surveys are rendered.

                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'TypeScript',
                                code: dedent`
                                    <PostHogProvider /*... your config ...*/>
                                        <PostHogSurveyProvider>
                                            <YourApp />
                                        </PostHogSurveyProvider>
                                    </PostHogProvider>
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        If you're not using the PostHogProvider, add PostHogSurveyProvider to your app anywhere inside your app root component.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'TypeScript',
                                code: dedent`
                                    <YourAppRoot>
                                        <PostHogSurveyProvider>
                                    </YourAppRoot>
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        You can also pass your client instance to the PostHogSurveyProvider.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'TypeScript',
                                code: dedent`
                                    <PostHogSurveyProvider client={posthog}>
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

export const ReactNativeInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getReactNativeSteps(CodeBlock, Markdown, dedent, snippets, { modifySteps })

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

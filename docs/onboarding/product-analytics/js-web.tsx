import { ReactNode } from 'react'

import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export interface StepDefinition {
    title: string
    badge?: 'required' | 'optional'
    content: ReactNode
}

export const getJSWebSteps = (CodeBlock: any, Markdown: any, dedent: any, snippets: any): StepDefinition[] => {
    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog JavaScript library using your package manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-js
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Import and initialize the PostHog library with your project API key and host:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'JavaScript',
                                code: dedent`
                                    import posthog from 'posthog-js'

                                    posthog.init('<ph_project_api_key>', {
                                        api_host: '<ph_client_api_host>',
                                        person_profiles: 'identified_only' // or 'always' to create profiles for anonymous users too
                                    })
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events to test your integration:
                    </Markdown>
                    {JSEventCapture && <JSEventCapture />}
                </>
            ),
        },
    ]
}

export const JSWebInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getJSWebSteps(CodeBlock, Markdown, dedent, snippets)

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

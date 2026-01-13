import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getGoSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog Go library:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    go get "github.com/posthog/posthog-go"
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>Initialize the PostHog client with your API key and host:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'go',
                                file: 'main.go',
                                code: dedent`
                                    package main

                                    import (
                                        "github.com/posthog/posthog-go"
                                    )

                                    func main() {
                                        client, _ := posthog.NewWithConfig("<ph_project_api_key>", posthog.Config{Endpoint: "<ph_client_api_host>"})
                                        defer client.Close()
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, you can manually send events to test your integration:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'go',
                                file: 'Go',
                                code: dedent`
                                    client.Enqueue(posthog.Capture{
                                        DistinctId: "user_123",
                                        Event: "button_clicked",
                                        Properties: posthog.NewProperties().
                                            Set("button_name", "signup"),
                                    })
                                `,
                            },
                        ]}
                    />
                    <PersonProfiles language="go" />
                </>
            ),
        },
    ]
}

export const GoInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getGoSteps(CodeBlock, Markdown, dedent)

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

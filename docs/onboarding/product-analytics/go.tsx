import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const GoInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the package" badge="required">
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
            </Step>

            <Step title="Configure PostHog" badge="required">
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
            </Step>

            <Step title="Send events">
                <Markdown>Capture custom events using the PostHog client:</Markdown>
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
            </Step>
        </Steps>
    )
}

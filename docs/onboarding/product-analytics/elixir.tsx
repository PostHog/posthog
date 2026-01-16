import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getElixirSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
    return [
        {
            title: 'Install',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the PostHog Elixir library to your `mix.exs` dependencies:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'elixir',
                                file: 'mix.exs',
                                code: dedent`
                                    def deps do
                                        [
                                            {:posthog, "~> 1.1.0"}
                                        ]
                                    end
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add your PostHog configuration to your config file:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'elixir',
                                file: 'config/config.exs',
                                code: dedent`
                                    config :posthog,
                                        api_url: "<ph_client_api_host>",
                                        api_key: "<ph_project_api_key>"
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
                                language: 'elixir',
                                file: 'Elixir',
                                code: dedent`
                                    Posthog.capture("user_123", "button_clicked", %{
                                        button_name: "signup"
                                    })
                                `,
                            },
                        ]}
                    />
                    <PersonProfiles language="elixir" />
                </>
            ),
        },
    ]
}

export const ElixirInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getElixirSteps(CodeBlock, Markdown, dedent)

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

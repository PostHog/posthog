import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ElixirInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install">
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
            </Step>

            <Step title="Configure">
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
            </Step>
        </Steps>
    )
}

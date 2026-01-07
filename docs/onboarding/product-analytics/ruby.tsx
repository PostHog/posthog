import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const RubyInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the gem" badge="required">
                <Markdown>Add the PostHog Ruby gem to your Gemfile:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'Gemfile',
                            code: dedent`
                                gem "posthog-ruby"
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
                            language: 'ruby',
                            file: 'Ruby',
                            code: dedent`
                                posthog = PostHog::Client.new({
                                    api_key: "<ph_project_api_key>",
                                    host: "<ph_client_api_host>",
                                    on_error: Proc.new { |status, msg| print msg }
                                })
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
                            language: 'ruby',
                            file: 'Ruby',
                            code: dedent`
                                posthog.capture({
                                    distinct_id: 'user_123',
                                    event: 'button_clicked',
                                    properties: {
                                        button_name: 'signup'
                                    }
                                })
                            `,
                        },
                    ]}
                />
                <PersonProfiles language="ruby" />
            </Step>
        </Steps>
    )
}

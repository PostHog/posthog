import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getRubyOnRailsSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the gems',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Add the \`posthog-ruby\` and \`posthog-rails\` gems to your Gemfile:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'ruby',
                                file: 'Gemfile',
                                code: dedent`
                                    gem "posthog-ruby"
                                    gem "posthog-rails"
                                `,
                            },
                        ]}
                    />
                    <Markdown>Then run:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    bundle install
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Generate the initializer',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Run the install generator to create the PostHog initializer:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    rails generate posthog:install
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            This will create \`config/initializers/posthog.rb\` with sensible defaults and documentation.
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Update \`config/initializers/posthog.rb\` with your project API key and host:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'ruby',
                                file: 'config/initializers/posthog.rb',
                                code: dedent`
                                    PostHog.init do |config|
                                      config.api_key = '<ph_project_api_key>'
                                      config.host = '<ph_client_api_host>'
                                    end
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
                    <Markdown>Once installed, you can manually send events to test your integration:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'ruby',
                                file: 'Ruby',
                                code: dedent`
                                    PostHog.capture({
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
                </>
            ),
        },
    ]
}

export const RubyOnRailsInstallation = createInstallation(getRubyOnRailsSteps)

import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { PersonProfiles } from './_snippets/person-profiles'

export const getRubySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the gem',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
    ]
}

export const RubyInstallation = createInstallation(getRubySteps)

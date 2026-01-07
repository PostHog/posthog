import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const PHPInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the package" badge="required">
                <Markdown>Install the PostHog PHP library using Composer:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Terminal',
                            code: dedent`
                                composer require posthog/posthog-php
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
                            language: 'php',
                            file: 'PHP',
                            code: dedent`
                                PostHog\\PostHog::init(
                                    '<ph_project_api_key>',
                                    ['host' => '<ph_client_api_host>']
                                );
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
                            language: 'php',
                            file: 'PHP',
                            code: dedent`
                                PostHog::capture([
                                    'distinctId' => 'test-user',
                                    'event' => 'test-event',
                                ]);
                            `,
                        },
                    ]}
                />
                <PersonProfiles language="php" />
            </Step>
        </Steps>
    )
}

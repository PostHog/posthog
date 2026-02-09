import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { PersonProfiles } from './_snippets/person-profiles'

export const getPHPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
    ]
}

export const PHPInstallation = createInstallation(getPHPSteps)

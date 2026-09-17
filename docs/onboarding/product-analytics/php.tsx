import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPHPInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                    <Markdown>Initialize the PostHog client with your project token and host:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'php',
                                file: 'PHP',
                                code: dedent`
                                PostHog\\PostHog::init(
                                    '<ph_project_token>',
                                    ['host' => '<ph_client_api_host>']
                                );
                            `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const getPHPEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
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
            </>
        ),
    }
}

export const getPHPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getPHPInstallSteps(ctx),
    getPHPEventStep(ctx),
]

export const PHPInstallation = createInstallation(getPHPSteps)

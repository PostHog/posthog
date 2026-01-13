import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getPHPSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
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
                    <Markdown>
                        Once installed, you can manually send events to test your integration:
                    </Markdown>
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

export const PHPInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getPHPSteps(CodeBlock, Markdown, dedent)

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

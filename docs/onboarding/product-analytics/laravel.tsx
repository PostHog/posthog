import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const LaravelInstallation = (): JSX.Element => {
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
                <Markdown>
                    Initialize PostHog in the `boot` method of `app/Providers/AppServiceProvider.php`:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'php',
                            file: 'app/Providers/AppServiceProvider.php',
                            code: dedent`
                                <?php

                                namespace App\\Providers;

                                use Illuminate\\Support\\ServiceProvider;
                                use PostHog\\PostHog;

                                class AppServiceProvider extends ServiceProvider
                                {
                                    public function boot(): void
                                    {
                                        PostHog::init(
                                            '<ph_project_api_key>',
                                            [
                                                'host' => '<ph_client_api_host>'
                                            ]
                                        );
                                    }
                                }
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Send events" badge="optional">
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

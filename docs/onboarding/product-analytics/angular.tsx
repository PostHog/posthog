import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const AngularInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()

    const JSEventCapture = snippets?.JSEventCapture

    return (
        <Steps>
            <Step title="Install the package" badge="required">
                <Markdown>Install the PostHog JavaScript library using your package manager:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'npm',
                            code: dedent`
                                npm install posthog-js
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'yarn',
                            code: dedent`
                                yarn add posthog-js
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'pnpm',
                            code: dedent`
                                pnpm add posthog-js
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Add environment variables" badge="required">
                <Markdown>
                    Add your environment variables to your `.env` file and to your hosting provider:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: '.env',
                            code: dedent`
                                POSTHOG_KEY=<ph_project_api_key>
                                POSTHOG_HOST=<ph_client_api_host>
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Initialize PostHog" badge="required">
                <Markdown>
                    In your `src/main.ts`, initialize PostHog using your project API key and instance address:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'src/main.ts',
                            code: dedent`
                                import { bootstrapApplication } from '@angular/platform-browser';
                                import { appConfig } from './app/app.config';
                                import { AppComponent } from './app/app.component';
                                import posthog from 'posthog-js'

                                posthog.init(
                                  process.env.POSTHOG_KEY,
                                  {
                                    api_host: process.env.POSTHOG_HOST,
                                    person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users too
                                    defaults: '2025-11-30'
                                  }
                                )

                                bootstrapApplication(AppComponent, appConfig)
                                  .catch((err) => console.error(err));
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Send events">{JSEventCapture && <JSEventCapture />}</Step>
        </Steps>
    )
}

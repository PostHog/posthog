import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
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
                                      '<ph_project_api_key>',
                                      {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '2025-11-30'
                                      }
                                    )

                                    bootstrapApplication(AppComponent, appConfig)
                                      .catch((err) => console.error(err));
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const AngularInstallation = createInstallation(getAngularSteps)

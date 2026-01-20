import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const SentryInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the packages" badge="required">
                <Markdown>
                    Sentry is an error tracking platform. The PostHog-Sentry integration links error data to your
                    analytics, allowing you to see which users experienced errors.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Terminal',
                            code: dedent`
                                npm install --save posthog-js @sentry/browser
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Configure the integration" badge="required">
                <Markdown>Add the Sentry integration when initializing PostHog:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                import posthog from 'posthog-js'
                                import * as Sentry from '@sentry/browser'

                                // Initialize Sentry first
                                Sentry.init({
                                  dsn: 'your-sentry-dsn',
                                })

                                // Initialize PostHog with Sentry integration
                                posthog.init('<ph_project_api_key>', {
                                  api_host: '<ph_client_api_host>',
                                  defaults: '2025-11-30'
                                })

                                // Set PostHog session ID on Sentry scope
                                Sentry.getCurrentScope().setTag('posthog_session_id', posthog.get_session_id())
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="Full setup guide">
                    <Markdown>
                        This allows you to link Sentry errors to PostHog sessions. See the [Sentry integration
                        docs](https://posthog.com/docs/libraries/sentry) for the full setup guide.
                    </Markdown>
                </CalloutBox>
            </Step>
        </Steps>
    )
}

import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getElixirSteps as getElixirStepsPA } from '../product-analytics/elixir'
import { StepDefinition } from '../steps'

export const getElixirSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getElixirStepsPA(ctx)

    const configureStep: StepDefinition = {
        title: 'Configure error tracking',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Error tracking is enabled by default in the Elixir SDK. You can keep that explicit in your config and set your OTP app names so stack frames from your code are marked as in-app.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'elixir',
                            file: 'config/config.exs',
                            code: dedent`
                                config :posthog,
                                    api_host: "<ph_client_api_host>",
                                    api_key: "<ph_project_token>",
                                    enable_error_tracking: true,
                                    in_app_otp_apps: [:my_app]
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Confirm exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, configureStep, verifyStep]
}

export const ElixirInstallation = createInstallation(getElixirSteps)

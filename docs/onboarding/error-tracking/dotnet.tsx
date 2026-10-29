import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getDotNetInstallSteps } from '../product-analytics/dotnet'
import { StepDefinition } from '../steps'

export const getDotNetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getDotNetInstallSteps(ctx)

    const captureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Capture handled exceptions with \`CaptureException\` so they appear in Error tracking.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'csharp',
                            file: 'C#',
                            code: dedent`
                                using PostHog;

                                void CaptureCheckoutException(IPostHogClient posthog)
                                {
                                    try
                                    {
                                        throw new InvalidOperationException("Something went wrong");
                                    }
                                    catch (Exception exception)
                                    {
                                        posthog.CaptureException(
                                            exception,
                                            "user_distinct_id",
                                            new Dictionary<string, object>
                                            {
                                                ["route"] = "/checkout",
                                            },
                                            groups: null,
                                            sendFeatureFlags: false
                                        );

                                        throw;
                                    }
                                }
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

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, captureStep, verifyStep]
}

export const DotNetInstallation = createInstallation(getDotNetSteps)

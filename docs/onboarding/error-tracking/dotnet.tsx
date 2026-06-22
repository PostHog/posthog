import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getDotNetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installStep: StepDefinition = {
        title: 'Install the package',
        badge: 'required',
        content: (
            <>
                <Markdown>Install the PostHog package for your .NET app:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'ASP.NET Core',
                            code: dedent`
                                dotnet add package PostHog.AspNetCore
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Console or worker',
                            code: dedent`
                                dotnet add package PostHog
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const configureStep: StepDefinition = {
        title: 'Configure PostHog',
        badge: 'required',
        content: (
            <>
                <Markdown>Register PostHog and configure your project token and host:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'csharp',
                            file: 'Program.cs',
                            code: dedent`
                                using PostHog;

                                var builder = WebApplication.CreateBuilder(args);
                                builder.AddPostHog();
                            `,
                        },
                        {
                            language: 'json',
                            file: 'appsettings.json',
                            code: dedent`
                                {
                                  "PostHog": {
                                    "ProjectToken": "<ph_project_token>",
                                    "HostUrl": "<ph_client_api_host>"
                                  }
                                }
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

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

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [installStep, configureStep, captureStep, verifyStep]
}

export const DotNetInstallation = createInstallation(getDotNetSteps)

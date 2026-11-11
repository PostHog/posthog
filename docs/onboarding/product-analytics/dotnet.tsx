import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getDotNetInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
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
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For ASP.NET Core, register PostHog and configure your project token and host in \`appsettings.json\`. Outside ASP.NET Core, create a single \`PostHogClient\` and reuse it across your app.
                        `}
                    </Markdown>
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
                            {
                                language: 'csharp',
                                file: 'Console or worker',
                                code: dedent`
                                    using PostHog;

                                    // Disposing the client sends any queued events before your app exits
                                    await using var posthog = new PostHogClient(new PostHogOptions
                                    {
                                        ProjectToken = "<ph_project_token>",
                                        HostUrl = new Uri("<ph_client_api_host>"),
                                    });
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const getDotNetEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Send events',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Once installed, you can manually send events to test your integration. In ASP.NET Core, inject \`IPostHogClient\` where you need it:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'csharp',
                            file: 'C#',
                            code: dedent`
                                posthog.Capture(
                                    "distinct_id_of_the_user",
                                    "user_signed_up",
                                    properties: new()
                                    {
                                        ["login_type"] = "email",
                                        ["is_free_trial"] = true,
                                    }
                                );
                            `,
                        },
                    ]}
                />
            </>
        ),
    }
}

export const getDotNetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getDotNetInstallSteps(ctx),
    getDotNetEventStep(ctx),
]

export const DotNetInstallation = createInstallation(getDotNetSteps)

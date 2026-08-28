import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getUnitySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the Unity SDK',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Install PostHog through the Unity Package Manager:

                        1. Open **Window > Package Manager**.
                        2. Select **Add package from git URL** from the **+** menu.
                        3. Enter \`https://github.com/PostHog/posthog-unity.git?path=com.posthog.unity\`.

                        The SDK requires Unity 2021.3 LTS or later and the .NET Standard 2.1 API Compatibility Level.
                    `}
                </Markdown>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Open **Edit > Project Settings > PostHog**, enter your project token and host, and keep **Capture Exceptions** enabled. The Unity SDK captures exceptions automatically by default.

                            You can also configure the SDK in code:
                        `}
                    </Markdown>
                    <CodeBlock
                        language="csharp"
                        code={dedent`
                            using PostHogUnity;

                            PostHog.Setup(new PostHogConfig
                            {
                                ApiKey = "<ph_project_token>",
                                Host = "<ph_client_api_host>",
                                CaptureExceptions = true,
                                ExceptionDebounceIntervalMs = 1000,
                            });
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Capture handled exceptions',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Automatic capture covers exceptions reported through Unity's exception logging pipeline. Call \`CaptureException\` for handled exceptions that should still appear in Error tracking.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="csharp"
                        code={dedent`
                            try
                            {
                                SaveGame();
                            }
                            catch (Exception exception)
                            {
                                PostHog.CaptureException(exception);
                            }
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Verify error tracking',
            badge: 'recommended',
            checkpoint: true,
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Report a test exception through Unity's logger and confirm it appears in [Error tracking](https://app.posthog.com/error_tracking).
                        `}
                    </Markdown>
                    <CodeBlock
                        language="csharp"
                        code={dedent`
                            Debug.LogException(new InvalidOperationException("Automatic test exception from Unity"));
                            PostHog.Flush();
                        `}
                    />
                </>
            ),
        },
    ]
}

export const UnityInstallation = createInstallation(getUnitySteps)

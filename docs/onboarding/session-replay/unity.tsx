import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getUnitySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CalloutBox, CodeBlock, Markdown, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        {
            title: 'Install the Unity SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Session replay requires Unity 2021.3 LTS or later with the .NET Standard 2.1 API Compatibility Level.

                            In the Unity Editor:

                            1. Open **Window > Package Manager**.
                            2. Select **Add package from git URL** from the **+** menu.
                            3. Enter the following URL:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'text',
                                code: 'https://github.com/PostHog/posthog-unity.git?path=com.posthog.unity',
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Enable session recordings in project settings',
            badge: 'required',
            content: (
                <Markdown>
                    Go to your PostHog [Project Settings](https://us.posthog.com/settings/project-replay) and enable
                    **Record user sessions**. Session recordings will not work without this setting enabled.
                </Markdown>
            ),
        },
        {
            title: 'Configure PostHog with session replay',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Enable `SessionReplay` in your PostHog configuration. You can also configure session replay in
                        **Edit &gt; Project Settings &gt; PostHog** in the Unity Editor.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'csharp',
                                file: 'GameManager.cs',
                                code: dedent`
                                    using PostHogUnity;
                                    using PostHogUnity.SessionReplay;

                                    PostHog.Setup(new PostHogConfig
                                    {
                                        ApiKey = "<ph_project_token>",
                                        Host = "<ph_client_api_host>",
                                        SessionReplay = true,
                                        SessionReplayConfig = new PostHogSessionReplayConfig
                                        {
                                            ThrottleDelaySeconds = 1.0f,
                                            ScreenshotQuality = 80,
                                            ScreenshotScale = 0.75f,
                                            CaptureNetworkTelemetry = true,
                                            CaptureLogs = false,
                                            MinLogLevel = SessionReplayLogLevel.Error,
                                        }
                                    });
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        The SDK captures screenshots, touch and mouse input, and optional console logs. Session replay
                        requires `AsyncGPUReadback` support and is unavailable on WebGL.
                    </Markdown>
                    <CalloutBox type="caution" title="No masking support">
                        <Markdown>
                            The Unity SDK uses screenshot-based capture and cannot mask text, images, or other UI
                            elements. Screenshots may contain sensitive information. Do not display personal data or
                            secrets during recorded sessions.
                        </Markdown>
                    </CalloutBox>
                    <Markdown>
                        Unity session replay uses local SDK configuration. Configure capture options and sampling in
                        code when the SDK starts. See the [Unity session replay
                        docs](https://posthog.com/docs/session-replay/installation/unity) for all available options.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}

export const UnityInstallation = createInstallation(getUnitySteps)

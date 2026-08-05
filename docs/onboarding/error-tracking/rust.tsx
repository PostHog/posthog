import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getRustSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the Rust SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Install the PostHog Rust SDK. Error tracking is enabled by its default \`error-tracking\` feature.
                        `}
                    </Markdown>
                    <CodeBlock language="bash" code="cargo add posthog-rs" />
                    <Markdown>
                        {dedent`
                            If you disable default features, add \`error-tracking\` explicitly in your dependency configuration.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="toml"
                        code={dedent`
                            [dependencies]
                            posthog-rs = { version = "*", default-features = false, features = ["async-client", "error-tracking"] }
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize the client',
            badge: 'required',
            content: (
                <CodeBlock
                    language="rust"
                    code={dedent`
                        let client = posthog_rs::client((
                            "<ph_project_token>",
                            "<ph_client_api_host>",
                        )).await;
                    `}
                />
            ),
        },
        {
            title: 'Capture handled exceptions',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            \`capture_exception\` accepts any \`std::error::Error\`. It captures the exception type, message, source chain, and a stack trace from the call site.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="rust"
                        code={dedent`
                            let error = std::io::Error::new(
                                std::io::ErrorKind::Other,
                                "connection refused",
                            );

                            client.capture_exception(&error).await.unwrap();
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Capture panics automatically',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Panic autocapture is opt-in. It requires the process-global client because the SDK installs one process-wide panic hook.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="rust"
                        code={dedent`
                            use posthog_rs::{ClientOptionsBuilder, ErrorTrackingOptionsBuilder};

                            let options = ClientOptionsBuilder::default()
                                .api_key("<ph_project_token>".to_string())
                                .host("<ph_client_api_host>")
                                .error_tracking(
                                    ErrorTrackingOptionsBuilder::default()
                                        .capture_panics(true)
                                        .build()
                                        .unwrap(),
                                )
                                .build()
                                .unwrap();

                            posthog_rs::init_global(options).await.unwrap();
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
                <Markdown>
                    {dedent`
                        Capture a test error and confirm it appears in [Error tracking](https://app.posthog.com/error_tracking).
                    `}
                </Markdown>
            ),
        },
    ]
}

export const RustInstallation = createInstallation(getRustSteps)

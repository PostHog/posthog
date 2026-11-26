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
                    <CodeBlock
                        language="bash"
                        code="cargo add posthog@1 tokio --features tokio/rt-multi-thread,tokio/macros"
                    />
                    <Markdown>
                        {dedent`
                            If you disable default features, add \`error-tracking\` and \`tls\` explicitly in your dependency configuration. Without \`tls\`, the SDK can't send to an HTTPS host.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="toml"
                        code={dedent`
                            [dependencies]
                            posthog = { version = "1", default-features = false, features = ["async-client", "error-tracking", "tls"] }
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
                        #[tokio::main]
                        async fn main() {
                            let client = posthog::client((
                                "<ph_project_token>",
                                "<ph_client_api_host>",
                            )).await;

                            // Capture events and exceptions here

                            // Shut down last, before the process exits. It flushes queued
                            // events, and the client drops anything captured after it.
                            client.shutdown().await;
                        }
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
                            use posthog::{ClientOptionsBuilder, ErrorTrackingOptionsBuilder};

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

                            posthog::init_global(options).await.unwrap();
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
                        Capture a test error and confirm it appears in [Error tracking](https://app.posthog.com/error-tracking).
                    `}
                </Markdown>
            ),
        },
    ]
}

export const RustInstallation = createInstallation(getRustSteps)

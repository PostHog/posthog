import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const LiteLLMInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, ProductScreenshot, OSButton, Markdown, Blockquote, dedent, snippets } =
        useMDXComponents()

    const NotableGenerationProperties = snippets?.NotableGenerationProperties
    return (
        <Steps>
            <Blockquote>
                <Markdown>
                    **Note:** LiteLLM can be used as a Python SDK or as a proxy server. PostHog observability requires
                    LiteLLM version 1.77.3 or higher.
                </Markdown>
            </Blockquote>

            <Step title="Install LiteLLM" badge="required">
                <Markdown>Choose your installation method based on how you want to use LiteLLM:</Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'SDK',
                            code: dedent`
                                pip install litellm
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Proxy',
                            code: dedent`
                                # Install via pip
                                pip install 'litellm[proxy]'

                                # Or run via Docker
                                docker run --rm -p 4000:4000 ghcr.io/berriai/litellm:latest
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Configure PostHog observability" badge="required">
                <Markdown>
                    Configure PostHog by setting your project API key and host as well as adding `posthog` to your
                    LiteLLM callback handlers. You can find your API key in [your project
                    settings](https://app.posthog.com/settings/project).
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'SDK',
                            code: dedent`
                                import os
                                import litellm

                                # Set environment variables
                                os.environ["POSTHOG_API_KEY"] = "<ph_project_api_key>"
                                os.environ["POSTHOG_API_URL"] = "<ph_client_api_host>"  # Optional, defaults to https://app.posthog.com

                                # Enable PostHog callbacks
                                litellm.success_callback = ["posthog"]
                                litellm.failure_callback = ["posthog"]  # Optional: also log failures
                            `,
                        },
                        {
                            language: 'yaml',
                            file: 'Proxy',
                            code: dedent`
                                # config.yaml
                                model_list:
                                - model_name: gpt-4o-mini
                                  litellm_params:
                                    model: gpt-4o-mini

                                litellm_settings:
                                  success_callback: ["posthog"]
                                  failure_callback: ["posthog"]  # Optional: also log failures

                                environment_variables:
                                  POSTHOG_API_KEY: "<ph_project_api_key>"
                                  POSTHOG_API_URL: "<ph_client_api_host>"  # Optional
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Call LLMs through LiteLLM" badge="required">
                <Markdown>
                    Now, when you use LiteLLM to call various LLM providers, PostHog automatically captures an
                    `$ai_generation` event.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'SDK',
                            code: dedent`
                                response = litellm.completion(
                                    model="gpt-4o-mini",
                                    messages=[
                                        {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                    ],
                                    metadata={
                                        "user_id": "user_123",  # Maps to PostHog distinct_id
                                        "company": "company_id_in_your_db"  # Custom property
                                    }
                                )

                                print(response.choices[0].message.content)
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Proxy',
                            code: dedent`
                                # Start the proxy (if not already running)
                                litellm --config config.yaml

                                # Make a request to the proxy
                                curl -X POST http://localhost:4000/chat/completions \
                                  -H "Content-Type: application/json" \
                                  -d '{
                                    "model": "gpt-4o-mini",
                                    "messages": [
                                      {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                    ],
                                    "metadata": {
                                      "user_id": "user_123",
                                      "company": "company_id_in_your_db" # Custom property
                                    }
                                  }'
                            `,
                        },
                    ]}
                />

                <Blockquote>
                    <Markdown>
                        {dedent`
                            **Notes:**
                            - This works with streaming responses by setting \`stream=True\`.
                            - To disable logging for specific requests, add \`{"no-log": true}\` to metadata.
                            - If you want to capture LLM events anonymously, **don't** pass a \`user_id\` in metadata.

                            See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        `}
                    </Markdown>
                </Blockquote>

                <Markdown>
                    {dedent`
                        You can expect captured \`$ai_generation\` events to have the following properties:
                    `}
                </Markdown>

                {NotableGenerationProperties && <NotableGenerationProperties />}
            </Step>

            <Step
                checkpoint
                title="Verify traces and generations"
                subtitle="Confirm LLM events are being sent to PostHog"
                docsOnly
            >
                <Markdown>
                    Let's make sure LLM events are being captured and sent to PostHog. Under **LLM analytics**, you
                    should see rows of data appear in the **Traces** and **Generations** tabs.
                </Markdown>

                <br />
                <ProductScreenshot
                    imageLight="https://res.cloudinary.com/dmukukwp6/image/upload/SCR_20250807_syne_ecd0801880.png"
                    imageDark="https://res.cloudinary.com/dmukukwp6/image/upload/SCR_20250807_syjm_5baab36590.png"
                    alt="LLM generations in PostHog"
                    classes="rounded"
                    className="mt-10"
                    padding={false}
                />

                <OSButton
                    variant="secondary"
                    asLink
                    className="my-2"
                    size="sm"
                    to="https://app.posthog.com/llm-analytics/generations"
                    external
                >
                    Check for LLM events in PostHog
                </OSButton>
            </Step>

            <Step title="Capture embeddings" badge="optional">
                <Markdown>
                    PostHog can also capture embedding generations as `$ai_embedding` events through LiteLLM:
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'SDK',
                            code: dedent`
                                response = litellm.embedding(
                                    input="The quick brown fox",
                                    model="text-embedding-3-small",
                                    metadata={
                                        "user_id": "user_123",  # Maps to PostHog distinct_id
                                        "company": "company_id_in_your_db"  # Custom property
                                    }
                                )
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Proxy',
                            code: dedent`
                                # Make an embeddings request to the proxy
                                curl -X POST http://localhost:4000/embeddings \
                                  -H "Content-Type: application/json" \
                                  -d '{
                                    "input": "The quick brown fox",
                                    "model": "text-embedding-3-small",
                                    "metadata": {
                                      "user_id": "user_123",
                                      "company": "company_id_in_your_db" # Custom property
                                    }
                                  }'
                            `,
                        },
                    ]}
                />
            </Step>
        </Steps>
    )
}

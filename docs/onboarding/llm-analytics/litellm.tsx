import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLiteLLMSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent, snippets } = ctx
    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'LiteLLM Requirements',
            badge: 'required',
            content: (
                <Blockquote>
                    <Markdown>
                        **Note:** LiteLLM can be used as a Python SDK or as a proxy server. PostHog observability requires
                        LiteLLM version 1.77.3 or higher.
                    </Markdown>
                </Blockquote>
            ),
        },
        {
            title: 'Install LiteLLM',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Configure PostHog observability',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Call LLMs through LiteLLM',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Capture embeddings',
            badge: 'optional',
            content: (
                <>
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
                </>
            ),
        },
    ]
}

export const LiteLLMInstallation = createInstallation(getLiteLLMSteps)

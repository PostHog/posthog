import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

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
                        **Note:** LiteLLM can be used as a Python SDK or as a proxy server. PostHog observability
                        requires LiteLLM version 1.77.3 or higher.
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
                        Configure PostHog by setting your project token and host as well as adding `posthog` to your
                        LiteLLM callback handlers. You can find your project token in [your project
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
                                    os.environ["POSTHOG_API_KEY"] = "<ph_project_token>"
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
                                    - model_name: gpt-5-mini
                                      litellm_params:
                                        model: gpt-5-mini

                                    litellm_settings:
                                      success_callback: ["posthog"]
                                      failure_callback: ["posthog"]  # Optional: also log failures

                                    environment_variables:
                                      POSTHOG_API_KEY: "<ph_project_token>"
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
                                        model="gpt-5-mini",
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        metadata={
                                            "user_id": "user_123",  # Maps to PostHog distinct_id
                                            "company": "company_id_in_your_db",  # Custom property
                                            "$ai_session_id": "conversation-abc"  # Groups calls into one session
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
                                        "model": "gpt-5-mini",
                                        "messages": [
                                          {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        "metadata": {
                                          "user_id": "user_123",
                                          "company": "company_id_in_your_db", # Custom property
                                          "$ai_session_id": "conversation-abc" # Groups calls into one session
                                        }
                                      }'
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            \`user_id\` in \`metadata\` ties this call to a person, mapped to PostHog's
                            \`distinct_id\`, so you can see everything one user asked for and know who hit an error
                            or ran up cost. \`$ai_session_id\` groups every call in one conversation, so a
                            multi-turn exchange reads as a single thread instead of separate, unrelated calls. A
                            trace covers one call, and a session covers the whole conversation: passing the same
                            session id across every call is what connects them. Together, they give you a complete
                            view: who made the request, which conversation it's part of, and every generation and
                            tool call inside it.
                        `}
                    </Markdown>

                    <Blockquote>
                        <Markdown>
                            {dedent`
                                **Notes:**
                                - This works with streaming responses by setting \`stream=True\`.
                                - To disable logging for specific requests, add \`{"no-log": true}\` to metadata.
                                - Pass \`$ai_session_id\` in metadata to group calls from the same conversation into
                                  one PostHog session.
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
            title: 'Capture tool calls as spans',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            LiteLLM's PostHog callback captures the \`$ai_generation\` event for the LLM call, but
                            it never sees the tools you call after that, and it has no \`posthog_trace_id\`
                            parameter to tie a span to a specific generation. Pass the trace id through \`metadata\`
                            instead, the same way \`$ai_session_id\` already travels, then capture the tool call
                            yourself as an \`$ai_span\` event.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            Here's a tool call captured as a span right after the generation that triggered it. Both
                            share the same \`$ai_trace_id\` and \`$ai_session_id\`, passed through \`metadata\` since
                            LiteLLM has no dedicated trace parameter. \`posthog\` is a raw PostHog client you create
                            for this, separate from the callback LiteLLM uses to send the generation.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            import time, uuid, json

                            posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                            session_id = "conversation-abc"  # same across every turn of the conversation
                            trace_id = str(uuid.uuid4())     # one per turn
                            user_id = "user_123"

                            # tools and get_weather() are your existing tool-calling setup
                            response = litellm.completion(
                                model="gpt-5-mini",
                                messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                tools=tools,
                                metadata={
                                    "user_id": user_id,
                                    "$ai_session_id": session_id,
                                    "$ai_trace_id": trace_id,
                                },
                            )

                            # Capture each tool call as a span nested under the generation above
                            for call in response.choices[0].message.tool_calls or []:
                                start = time.time()
                                result = get_weather(**json.loads(call.function.arguments))

                                posthog.capture(
                                    distinct_id=user_id,
                                    event="$ai_span",
                                    properties={
                                        "$ai_trace_id": trace_id,
                                        "$ai_session_id": session_id,
                                        "$ai_span_id": str(uuid.uuid4()),
                                        "$ai_span_name": call.function.name,
                                        "$ai_input_state": call.function.arguments,
                                        "$ai_output_state": result,
                                        "$ai_latency": time.time() - start,
                                    },
                                )
                        `}
                    />

                    <Markdown>
                        {dedent`
                            The span must carry the same \`$ai_trace_id\` as the generation it belongs to, or it
                            won't nest under the same trace. Nothing measures duration for you: time your own code
                            and pass the result as \`$ai_latency\`. Set \`$ai_span_type\` to describe the kind of
                            work, for example \`tool\`, \`chain\`, \`retriever\`, or \`agent\`.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            See [spans](https://posthog.com/docs/ai-observability/spans) for the full list of span
                            properties.
                        `}
                    </Markdown>
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

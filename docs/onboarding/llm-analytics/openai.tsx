import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getOpenAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK for your language. LLM analytics works
                        best with our Python and Node SDKs.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Install the OpenAI SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the OpenAI SDK. The PostHog SDK instruments your LLM calls by wrapping the OpenAI client. The
                        PostHog SDK **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install openai
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and OpenAI client',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then pass it to our OpenAI wrapper.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog.ai.openai import OpenAI
                                    from posthog import Posthog

                                    posthog = Posthog(
                                        "<ph_project_api_key>",
                                        host="<ph_client_api_host>"
                                    )

                                    client = OpenAI(
                                        api_key="your_openai_api_key",
                                        posthog_client=posthog # This is an optional parameter. If it is not provided, a default client will be used.
                                    )
                                `,
                            },
                            {
                                language: 'ts',
                                file: 'Node',
                                code: dedent`
                                    import { OpenAI } from '@posthog/ai'
                                    import { PostHog } from 'posthog-node'

                                    const phClient = new PostHog(
                                      '<ph_project_api_key>',
                                      { host: '<ph_client_api_host>' }
                                    );

                                    const openai = new OpenAI({
                                      apiKey: 'your_openai_api_key',
                                      posthog: phClient,
                                    });

                                    // ... your code here ...

                                    // IMPORTANT: Shutdown the client when you're done to ensure all events are sent
                                    phClient.shutdown()
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>**Note:** This also works with the `AsyncOpenAI` client.</Markdown>
                    </Blockquote>

                    <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the
                            background to send the data. You can also use LLM analytics with other SDKs or our API, but you
                            will need to capture the data in the right format. See the schema in the [manual capture
                            section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Call OpenAI LLMs',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when you use the OpenAI SDK to call LLMs, PostHog automatically captures an `$ai_generation`
                        event. You can enrich the event with additional data such as the trace ID, distinct ID, custom
                        properties, groups, and privacy mode options.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.responses.create(
                                        model="gpt-4o-mini",
                                        input=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        posthog_distinct_id="user_123", # optional
                                        posthog_trace_id="trace_123", # optional
                                        posthog_properties={"conversation_id": "abc123", "paid": True}, # optional
                                        posthog_groups={"company": "company_id_in_your_db"},  # optional
                                        posthog_privacy_mode=False # optional
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'ts',
                                file: 'Node',
                                code: dedent`
                                    const completion = await openai.responses.create({
                                        model: "gpt-4o-mini",
                                        input: [{ role: "user", content: "Tell me a fun fact about hedgehogs" }],
                                        posthogDistinctId: "user_123", // optional
                                        posthogTraceId: "trace_123", // optional
                                        posthogProperties: { conversation_id: "abc123", paid: true }, // optional
                                        posthogGroups: { company: "company_id_in_your_db" }, // optional
                                        posthogPrivacyMode: false // optional
                                    });

                                    console.log(completion.choices[0].message.content)
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            {dedent`
                            **Notes:**
                            - We also support the old \`chat.completions\` API.
                            - This works with responses where \`stream=True\`.
                            - If you want to capture LLM events anonymously, **don't** pass a distinct ID to the request.

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
                        PostHog can also capture embedding generations as `$ai_embedding` events. Just make sure to use the
                        same `posthog.ai.openai` client to do so:
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            response = client.embeddings.create(
                                input="The quick brown fox",
                                model="text-embedding-3-small",
                                posthog_distinct_id="user_123", # optional
                                posthog_trace_id="trace_123",   # optional
                                posthog_properties={"key": "value"} # optional
                                posthog_groups={"company": "company_id_in_your_db"}  # optional
                                posthog_privacy_mode=False # optional
                            )
                        `}
                    />
                </>
            ),
        },
    ]
}

export const OpenAIInstallation = createInstallation(getOpenAISteps)

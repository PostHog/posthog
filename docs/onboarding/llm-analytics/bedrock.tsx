import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getBedrockSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install PostHog and Anthropic SDKs',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog and Anthropic SDKs.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install posthog anthropic
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and Bedrock client',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        We call Amazon Bedrock through the Anthropic client and generate a response. We'll use PostHog's
                        Anthropic Bedrock provider to capture all the details of the call. Initialize PostHog with your
                        PostHog project API key and host from [your project settings](https://app.posthog.com/settings/project),
                        then pass the PostHog client along with your AWS region to our Anthropic Bedrock wrapper.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog.ai.anthropic import AnthropicBedrock
                            from posthog import Posthog

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            client = AnthropicBedrock(
                                aws_region="us-east-1",
                                posthog_client=posthog
                            )
                        `}
                    />

                    <Blockquote>
                        <Markdown>**Note:** This also works with the `AsyncAnthropicBedrock` client.</Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Call Amazon Bedrock',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when you call Amazon Bedrock with the Anthropic SDK, PostHog automatically captures an
                        `$ai_generation` event. You can also capture or modify additional properties with the distinct ID,
                        trace ID, properties, groups, and privacy mode parameters.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            message = client.messages.create(
                                model="anthropic.claude-sonnet-4-20250514",
                                max_tokens=1024,
                                messages=[
                                    {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                ],
                                posthog_distinct_id="user_123", # optional
                                posthog_trace_id="trace_123", # optional
                                posthog_properties={"conversation_id": "abc123", "paid": True}, # optional
                                posthog_groups={"company": "company_id_in_your_db"},  # optional
                                posthog_privacy_mode=False # optional
                            )

                            print(message.content[0].text)
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            {dedent`
                            **Notes:**
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
    ]
}

export const BedrockInstallation = createInstallation(getBedrockSteps)

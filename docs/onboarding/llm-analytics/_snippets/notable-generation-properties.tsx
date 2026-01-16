import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const NotableGenerationProperties = (): JSX.Element => {
    const { Markdown, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    | Property  | Description |
                    |---------- | -------------|
                    | \`$ai_model\` | The specific model, like \`gpt-5-mini\` or \`claude-4-sonnet\` |
                    | \`$ai_latency\` | The latency of the LLM call in seconds |
                    | \`$ai_time_to_first_token\` | Time to first token in seconds (streaming only) |
                    | \`$ai_tools\` | Tools and functions available to the LLM |
                    | \`$ai_input\` | List of messages sent to the LLM |
                    | \`$ai_input_tokens\` | The number of tokens in the input (often found in response.usage) |
                    | \`$ai_output_choices\` | List of response choices from the LLM |
                    | \`$ai_output_tokens\` | The number of tokens in the output (often found in \`response.usage\`) |
                    | \`$ai_total_cost_usd\` | The total cost in USD (input + output) |
                    | [[...]](https://posthog.com/docs/llm-analytics/generations#event-properties) | See [full list](https://posthog.com/docs/llm-analytics/generations#event-properties) of properties|
                `}
            </Markdown>
        </>
    )
}


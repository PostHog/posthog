import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

const propertyColumnStyle = { minWidth: '150px' }

export const TraceEvent = (): JSX.Element => {
    const { Markdown, dedent, CodeBlock } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    A trace is a group that contains multiple spans, generations, and embeddings. Traces can be manually sent as events or appear as pseudo-events automatically created from child events.

                    **Event name**: \`$ai_trace\`

                    ### Core properties
                `}
            </Markdown>

            <div className="LemonMarkdown">
                <table className="my-4">
                    <thead>
                        <tr>
                            <th style={propertyColumnStyle}>Property</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_trace_id</code>
                        </td>
                        <td>
                            <p>
                                The trace ID (a UUID to group related AI events together)
                                <br />
                                Must contain only letters, numbers, and special characters: <code>-</code>, <code>_</code>, <code>~</code>, <code>.</code>, <code>@</code>, <code>(</code>, <code>)</code>, <code>!</code>, <code>'</code>, <code>:</code>, <code>|</code>
                                <br />
                                Example: <code>d9222e05-8708-41b8-98ea-d4a21849e761</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_session_id</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Groups related traces together. Use this to organize traces by whatever grouping makes sense for your application (user sessions, workflows, conversations, or other logical boundaries).
                                <br />
                                Example: <code>session-abc-123</code>, <code>conv-user-456</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input_state</code>
                        </td>
                        <td>
                            <p>
                                The input of the whole trace
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    [
                                      {
                                        "role": "user",
                                        "content": "What's the weather in SF?"
                                      }
                                    ]
                                `}
                            />
                            <p>or any JSON-serializable state</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_state</code>
                        </td>
                        <td>
                            <p>
                                The output of the whole trace
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    [
                                      {
                                        "role": "assistant",
                                        "content": "The weather in San Francisco is..."
                                      }
                                    ]
                                `}
                            />
                            <p>or any JSON-serializable state</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_latency</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The latency of the trace in seconds</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_span_name</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> The name of the trace
                                <br />
                                Example: <code>chat_completion</code>, <code>rag_pipeline</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_is_error</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Boolean to indicate if the trace encountered an error</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_error</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The error message or object if the trace failed</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>
                {dedent`
                    ### Pseudo-trace Events

                    When you send generation (\`$ai_generation\`), span (\`$ai_span\`), or embedding (\`$ai_embedding\`) events with a \`$ai_trace_id\`, PostHog automatically creates a pseudo-trace event that appears in the dashboard as a parent grouping. These pseudo-traces:

                    - Are not actual events in your data
                    - Automatically aggregate metrics from child events (latency, tokens, costs)
                    - Provide a hierarchical view of your AI operations
                    - Do not require sending an explicit \`$ai_trace\` event

                    This means you can either:
                    1. Send explicit \`$ai_trace\` events to control the trace metadata
                    2. Let PostHog automatically create pseudo-traces from your generation/span events
                `}
            </Markdown>

        </>
    )
}


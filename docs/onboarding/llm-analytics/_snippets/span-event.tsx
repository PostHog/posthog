import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

const propertyColumnStyle = { minWidth: '150px' }

export const SpanEvent = (): JSX.Element => {
    const { Markdown, dedent, CodeBlock } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    A span is a single action within your application, such as a function call or vector database search.

                    **Event name**: \`$ai_span\`

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
                                Must contain only letters, numbers, and the following characters: <code>-</code>, <code>_</code>, <code>~</code>, <code>.</code>, <code>@</code>, <code>(</code>, <code>)</code>, <code>!</code>, <code>'</code>, <code>:</code>, <code>|</code>
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
                            <code>$ai_span_id</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Unique identifier for this span
                                <br />
                                Example: <code>bdf42359-9364-4db7-8958-c001f28c9255</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_span_name</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> The name of the span
                                <br />
                                Example: <code>vector_search</code>, <code>data_retrieval</code>, <code>tool_call</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_parent_id</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Parent ID for tree view grouping (<code>trace_id</code> or another <code>span_id</code>)
                                <br />
                                Example: <code>537b7988-0186-494f-a313-77a5a8f7db26</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input_state</code>
                        </td>
                        <td>
                            <p>
                                The input state of the span
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    {
                                      "query": "search for documents about hedgehogs"
                                    }
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
                                The output state of the span
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    {
                                      "results": ["doc1", "doc2"],
                                      "count": 2
                                    }
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
                            <p>
                                <em>(Optional)</em> The latency of the span in seconds
                                <br />
                                Example: <code>0.361</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_is_error</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Boolean to indicate if the span encountered an error</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_error</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> The error message or object if the span failed
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    {
                                      "message": "Connection timeout",
                                      "code": "TIMEOUT"
                                    }
                                `}
                            />
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

        </>
    )
}


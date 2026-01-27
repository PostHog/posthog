import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

const propertyColumnStyle = { minWidth: '150px' }

export const EmbeddingEvent = (): JSX.Element => {
    const { Markdown, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    An embedding is a single call to an embedding model to convert text into a vector representation.

                    **Event name**: \`$ai_embedding\`

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
                                The trace ID (a UUID to group related AI events together). Must contain only letters, numbers, and special characters: <code>-</code>, <code>_</code>, <code>~</code>, <code>.</code>, <code>@</code>, <code>(</code>, <code>)</code>, <code>!</code>, <code>'</code>, <code>:</code>, <code>|</code>
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
                            <p><em>(Optional)</em> Unique identifier for this embedding operation</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_span_name</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Name given to this embedding operation
                                <br />
                                Example: <code>embed_user_query</code>, <code>index_document</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_parent_id</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Parent span ID for tree-view grouping</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_model</code>
                        </td>
                        <td>
                            <p>
                                The embedding model used
                                <br />
                                Example: <code>text-embedding-3-small</code>, <code>text-embedding-ada-002</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_provider</code>
                        </td>
                        <td>
                            <p>
                                The LLM provider
                                <br />
                                Example: <code>openai</code>, <code>cohere</code>, <code>voyage</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input</code>
                        </td>
                        <td>
                            <p>
                                The text to embed
                                <br />
                                Example: <code>"Tell me a fun fact about hedgehogs"</code> or array of strings for batch embeddings
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input_tokens</code>
                        </td>
                        <td>
                            <p>The number of tokens in the input</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_latency</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The latency of the embedding call in seconds</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_http_status</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The HTTP status code of the response</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_base_url</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> The base URL of the LLM provider
                                <br />
                                Example: <code>https://api.openai.com/v1</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_request_url</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> The full URL of the request made to the embedding API
                                <br />
                                Example: <code>https://api.openai.com/v1/embeddings</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_is_error</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Boolean to indicate if the request was an error</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_error</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The error message or object if the embedding failed</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>
                {dedent`
                    ### Cost properties

                    Cost properties are optional as we can automatically calculate them from model and token counts. If you want, you can provide your own cost property instead.
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
                            <code>$ai_input_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Cost in USD for input tokens</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Cost in USD for output tokens (usually 0 for embeddings)</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_total_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Total cost in USD</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>
        </>
    )
}


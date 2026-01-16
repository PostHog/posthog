import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

const propertyColumnStyle = { minWidth: '150px' }

export const GenerationEvent = (): JSX.Element => {
    const { Markdown, dedent, CodeBlock } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    A generation is a single call to an LLM.

                    **Event name**: \`$ai_generation\`

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
                                The trace ID (a UUID to group AI events) like <code>conversation_id</code>
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
                            <code>$ai_span_id</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Unique identifier for this generation</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_span_name</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Name given to this generation
                                <br />
                                Example: <code>summarize_text</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_parent_id</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Parent span ID for tree view grouping</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_model</code>
                        </td>
                        <td>
                            <p>
                                The model used
                                <br />
                                Example: <code>gpt-5-mini</code>
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
                                Example: <code>openai</code>, <code>anthropic</code>, <code>gemini</code>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input</code>
                        </td>
                        <td>
                            <p>
                                List of messages sent to the LLM. Each message should have a <code>role</code> property with one of: <code>"user"</code>, <code>"system"</code>, or <code>"assistant"</code>
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    [
                                      {
                                        "role": "user",
                                        "content": [
                                          {
                                            "type": "text",
                                            "text": "What's in this image?"
                                          },
                                          {
                                            "type": "image",
                                            "image": "https://example.com/image.jpg"
                                          },
                                          {
                                            "type": "function",
                                            "function": {
                                              "name": "get_weather",
                                              "arguments": {
                                                "location": "San Francisco"
                                              }
                                            }
                                          }
                                        ]
                                      }
                                    ]
                                `}
                            />
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_input_tokens</code>
                        </td>
                        <td>
                            <p>The number of tokens in the input (often found in response.usage)</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_choices</code>
                        </td>
                        <td>
                            <p>
                                List of response choices from the LLM. Each choice should have a <code>role</code> property with one of: <code>"user"</code>, <code>"system"</code>, or <code>"assistant"</code>
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    [
                                      {
                                        "role": "assistant",
                                        "content": [
                                          {
                                            "type": "text",
                                            "text": "I can see a hedgehog in the image."
                                          },
                                          {
                                            "type": "function",
                                            "function": {
                                              "name": "get_weather",
                                              "arguments": {
                                                "location": "San Francisco"
                                              }
                                            }
                                          }
                                        ]
                                      }
                                    ]
                                `}
                            />
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_tokens</code>
                        </td>
                        <td>
                            <p>The number of tokens in the output (often found in response.usage)</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_latency</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The latency of the LLM call in seconds</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_time_to_first_token</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Time to first token in seconds. Only applicable for streaming responses.</p>
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
                                <em>(Optional)</em> The full URL of the request made to the LLM API
                                <br />
                                Example: <code>https://api.openai.com/v1/chat/completions</code>
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
                            <p><em>(Optional)</em> The error message or object</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>
                {dedent`
                    ### Cost properties

                    Cost properties are optional as we can automatically calculate them from model and token counts. If you want, you can provide your own cost properties or custom pricing instead.

                    #### Pre-calculated costs
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
                            <p><em>(Optional)</em> The cost in USD of the input tokens</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The cost in USD of the output tokens</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_request_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The cost in USD for the requests</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_web_search_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The cost in USD for the web searches</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_total_cost_usd</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> The total cost in USD (sum of all cost components)</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>#### Custom pricing</Markdown>

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
                            <code>$ai_input_token_price</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Price per input token (used to calculate <code>$ai_input_cost_usd</code>)
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_output_token_price</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Price per output token (used to calculate <code>$ai_output_cost_usd</code>)
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_cache_read_token_price</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Price per cached token read</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_cache_write_token_price</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Price per cached token write</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_request_price</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Price per request</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_request_count</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Number of requests (defaults to 1 if <code>$ai_request_price</code> is set)
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_web_search_price</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Price per web search</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_web_search_count</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Number of web searches performed</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>### Cache properties</Markdown>

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
                            <code>$ai_cache_read_input_tokens</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Number of tokens read from cache</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_cache_creation_input_tokens</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Number of tokens written to cache (Anthropic-specific)</p>
                        </td>
                    </tr>
                    </tbody>
                </table>
            </div>

            <Markdown>### Model parameters</Markdown>

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
                            <code>$ai_temperature</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Temperature parameter used in the LLM request</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_stream</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Whether the response was streamed</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_max_tokens</code>
                        </td>
                        <td>
                            <p><em>(Optional)</em> Maximum tokens setting for the LLM response</p>
                        </td>
                    </tr>
                    <tr>
                        <td style={propertyColumnStyle}>
                            <code>$ai_tools</code>
                        </td>
                        <td>
                            <p>
                                <em>(Optional)</em> Tools/functions available to the LLM
                                <br />
                                Example:
                            </p>
                            <CodeBlock
                                language="json"
                                code={dedent`
                                    [
                                      {
                                        "type": "function",
                                        "function": {
                                          "name": "get_weather",
                                          "parameters": {}
                                        }
                                      }
                                    ]
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

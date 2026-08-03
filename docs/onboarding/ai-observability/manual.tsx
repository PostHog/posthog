import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getManualSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, Tab, CodeBlock, snippets, dedent } = ctx

    const GenerationEvent = snippets?.GenerationEvent
    const TraceEvent = snippets?.TraceEvent
    const SpanEvent = snippets?.SpanEvent
    const EmbeddingEvent = snippets?.EmbeddingEvent

    const languages = [
        { key: 'API', label: 'API' },
        { key: 'Node.js', label: 'Node.js' },
        { key: 'Python', label: 'Python' },
        { key: 'Go', label: 'Go' },
        { key: 'Ruby', label: 'Ruby' },
        { key: 'PHP', label: 'PHP' },
    ]

    return [
        {
            title: 'Capture LLM events manually',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            If you use a different server-side SDK, or prefer to use the API, capture the data
                            manually. Call the \`capture\` method, or use the [capture
                            API](https://posthog.com/docs/api/capture).
                        `}
                    </Markdown>

                    <Tab.Group tabs={languages.map((l) => l.label)}>
                        <Tab.List>
                            {languages.map((l) => (
                                <Tab key={l.key}>{l.label}</Tab>
                            ))}
                        </Tab.List>
                        <Tab.Panels>
                            {languages.map((l) => (
                                <Tab.Panel key={l.key}>
                                    <>
                                        {l.key === 'Node.js' && (
                                            <>
                                                <Markdown>### 1. Install</Markdown>
                                                <CodeBlock language="bash" code="npm install posthog-node" />

                                                <Markdown>### 2. Initialize PostHog</Markdown>
                                                <CodeBlock
                                                    language="javascript"
                                                    code={dedent`
                                                        import { PostHog } from 'posthog-node'

                                                        const client = new PostHog('<ph_project_token>', {
                                                            host: '<ph_client_api_host>'
                                                        })
                                                    `}
                                                />

                                                <Markdown>### 3. Capture Event</Markdown>
                                                <CodeBlock
                                                    language="javascript"
                                                    code={dedent`
                                                        // After your LLM call
                                                        client.capture({
                                                            distinctId: 'user_123',
                                                            event: '$ai_generation',
                                                            properties: {
                                                                $ai_trace_id: 'trace_id_here',
                                                                $ai_model: 'gpt-5-mini',
                                                                $ai_provider: 'openai',
                                                                $ai_input: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                                                $ai_input_tokens: 10,
                                                                $ai_output_choices: [{ role: 'assistant', content: 'Hedgehogs have around 5,000 to 7,000 spines on their backs!' }],
                                                                $ai_output_tokens: 20,
                                                                $ai_latency: 1.5,
                                                                // For streaming responses, also include:
                                                                // $ai_stream: true,
                                                                // $ai_time_to_first_token: 0.25
                                                            }
                                                        })

                                                        client.shutdown()
                                                    `}
                                                />
                                            </>
                                        )}

                                        {l.key === 'Python' && (
                                            <>
                                                <Markdown>### 1. Install</Markdown>
                                                <CodeBlock language="bash" code="pip install posthog" />

                                                <Markdown>### 2. Initialize PostHog</Markdown>
                                                <CodeBlock
                                                    language="python"
                                                    code={dedent`
                                                        from posthog import Posthog

                                                        posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")
                                                    `}
                                                />

                                                <Markdown>### 3. Capture Event</Markdown>
                                                <CodeBlock
                                                    language="python"
                                                    code={dedent`
                                                        # After your LLM call
                                                        posthog.capture(
                                                            distinct_id='user_123',
                                                            event='$ai_generation',
                                                            properties={
                                                                '$ai_trace_id': 'trace_id_here',
                                                                '$ai_model': 'gpt-5-mini',
                                                                '$ai_provider': 'openai',
                                                                '$ai_input': [{'role': 'user', 'content': 'Tell me a fun fact about hedgehogs'}],
                                                                '$ai_input_tokens': 10,
                                                                '$ai_output_choices': [{'role': 'assistant', 'content': 'Hedgehogs have around 5,000 to 7,000 spines on their backs!'}],
                                                                '$ai_output_tokens': 20,
                                                                '$ai_latency': 1.5,
                                                                # For streaming responses, also include:
                                                                # '$ai_stream': True,
                                                                # '$ai_time_to_first_token': 0.25
                                                            }
                                                        )
                                                    `}
                                                />
                                            </>
                                        )}

                                        {l.key === 'Go' && (
                                            <>
                                                <Markdown>### 1. Install</Markdown>
                                                <CodeBlock
                                                    language="bash"
                                                    code="go get github.com/posthog/posthog-go"
                                                />

                                                <Markdown>### 2. Initialize PostHog</Markdown>
                                                <CodeBlock
                                                    language="go"
                                                    code={dedent`
                                                        import "github.com/posthog/posthog-go"

                                                        client, _ := posthog.NewWithConfig("<ph_project_token>", posthog.Config{
                                                            Endpoint: "<ph_client_api_host>",
                                                        })
                                                        defer client.Close()
                                                    `}
                                                />

                                                <Markdown>### 3. Capture Event</Markdown>
                                                <CodeBlock
                                                    language="go"
                                                    code={dedent`
                                                        // After your LLM call
                                                        client.Enqueue(posthog.Capture{
                                                            DistinctId: "user_123",
                                                            Event:      "$ai_generation",
                                                            Properties: map[string]interface{}{
                                                                "$ai_trace_id":        "trace_id_here",
                                                                "$ai_model":           "gpt-5-mini",
                                                                "$ai_provider":        "openai",
                                                                "$ai_input_tokens":    10,
                                                                "$ai_output_tokens":   20,
                                                                "$ai_latency":         1.5,
                                                                // For streaming responses, also include:
                                                                // "$ai_stream":              true,
                                                                // "$ai_time_to_first_token": 0.25,
                                                            },
                                                        })
                                                    `}
                                                />
                                            </>
                                        )}

                                        {l.key === 'Ruby' && (
                                            <>
                                                <Markdown>### 1. Install</Markdown>
                                                <CodeBlock language="bash" code="gem install posthog-ruby" />

                                                <Markdown>### 2. Initialize PostHog</Markdown>
                                                <CodeBlock
                                                    language="ruby"
                                                    code={dedent`
                                                        require 'posthog'

                                                        posthog = PostHog::Client.new({
                                                            api_key: '<ph_project_token>',
                                                            host: '<ph_client_api_host>'
                                                        })
                                                    `}
                                                />

                                                <Markdown>### 3. Capture Event</Markdown>
                                                <CodeBlock
                                                    language="ruby"
                                                    code={dedent`
                                                        # After your LLM call
                                                        posthog.capture({
                                                            distinct_id: 'user_123',
                                                            event: '$ai_generation',
                                                            properties: {
                                                            '$ai_trace_id' => 'trace_id_here',
                                                            '$ai_model' => 'gpt-5-mini',
                                                            '$ai_provider' => 'openai',
                                                            '$ai_input_tokens' => 10,
                                                            '$ai_output_tokens' => 20,
                                                            '$ai_latency' => 1.5
                                                            # For streaming responses, also include:
                                                            # '$ai_stream' => true,
                                                            # '$ai_time_to_first_token' => 0.25
                                                            }
                                                        })
                                                    `}
                                                />
                                            </>
                                        )}

                                        {l.key === 'PHP' && (
                                            <>
                                                <Markdown>### 1. Install</Markdown>
                                                <CodeBlock
                                                    language="bash"
                                                    code="composer require posthog/posthog-php"
                                                />

                                                <Markdown>### 2. Initialize PostHog</Markdown>
                                                <CodeBlock
                                                    language="php"
                                                    code={dedent`
                                                        <?php
                                                        require_once __DIR__ . '/vendor/autoload.php';
                                                        use PostHog\\PostHog;

                                                        PostHog::init('<ph_project_token>', [
                                                            'host' => '<ph_client_api_host>'
                                                        ]);
                                                    `}
                                                />

                                                <Markdown>### 3. Capture Event</Markdown>
                                                <CodeBlock
                                                    language="php"
                                                    code={dedent`
                                                        // After your LLM call
                                                        PostHog::capture([
                                                            'distinctId' => 'user_123',
                                                            'event' => '$ai_generation',
                                                            'properties' => [
                                                                '$ai_trace_id' => 'trace_id_here',
                                                                '$ai_model' => 'gpt-5-mini',
                                                                '$ai_provider' => 'openai',
                                                                '$ai_input_tokens' => 10,
                                                                '$ai_output_tokens' => 20,
                                                                '$ai_latency' => 1.5
                                                                // For streaming responses, also include:
                                                                // '$ai_stream' => true,
                                                                // '$ai_time_to_first_token' => 0.25
                                                            ]
                                                        ]);
                                                    `}
                                                />
                                            </>
                                        )}

                                        {l.key === 'API' && (
                                            <>
                                                <Markdown>### Capture via API</Markdown>
                                                <CodeBlock
                                                    language="bash"
                                                    code={dedent`
                                                        curl -X POST "<ph_client_api_host>/i/v0/e/" \\
                                                                -H "Content-Type: application/json" \\
                                                                -d '{
                                                                    "api_key": "<ph_project_token>",
                                                                    "event": "$ai_generation",
                                                                    "properties": {
                                                                        "distinct_id": "user_123",
                                                                        "$ai_trace_id": "trace_id_here",
                                                                        "$ai_model": "gpt-5-mini",
                                                                        "$ai_provider": "openai",
                                                                        "$ai_input": [{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
                                                                        "$ai_input_tokens": 10,
                                                                        "$ai_output_choices": [{"role": "assistant", "content": "Hedgehogs have around 5,000 to 7,000 spines on their backs!"}],
                                                                        "$ai_output_tokens": 20,
                                                                        "$ai_latency": 1.5,
                                                                        "$ai_stream": true,
                                                                        "$ai_time_to_first_token": 0.25
                                                                    }
                                                                }'
                                                    `}
                                                />
                                            </>
                                        )}
                                    </>
                                </Tab.Panel>
                            ))}
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
        {
            title: 'Capture tool calls and other spans',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Spans are other actions taken within a LLM trace, like tool calls or database queries. They can be captured using an \`$ai_span\` event.
                        `}
                    </Markdown>

                    <Tab.Group tabs={['Python', 'Node.js']}>
                        <Tab.List>
                            <Tab>Python</Tab>
                            <Tab>Node.js</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <CodeBlock
                                    language="python"
                                    code={dedent`
                                        from posthog import Posthog
                                        from posthog.ai.openai import OpenAI
                                        import time, uuid, json

                                        posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")
                                        client = OpenAI(api_key="your_openai_api_key", posthog_client=posthog)

                                        session_id = "conversation-abc"  # same across every turn of the conversation
                                        trace_id = str(uuid.uuid4())     # one per turn
                                        distinct_id = "user_123"

                                        # tools and get_weather() are your existing tool-calling setup
                                        response = client.chat.completions.create(
                                            model="gpt-4o-mini",
                                            messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                            tools=tools,
                                            posthog_distinct_id=distinct_id,
                                            posthog_trace_id=trace_id,
                                            posthog_properties={"$ai_session_id": session_id},
                                        )

                                        # Capture each tool call as a span nested under the generation above
                                        for call in response.choices[0].message.tool_calls or []:
                                            start = time.time()
                                            result = get_weather(**json.loads(call.function.arguments))

                                            posthog.capture(
                                                distinct_id=distinct_id,
                                                event="$ai_span",
                                                properties={
                                                    "$ai_trace_id": trace_id,               # ties the span to the generation
                                                    "$ai_session_id": session_id,           # ties it to the conversation
                                                    "$ai_span_id": str(uuid.uuid4()),
                                                    "$ai_span_name": call.function.name,
                                                    "$ai_input_state": call.function.arguments,
                                                    "$ai_output_state": result,
                                                    "$ai_latency": time.time() - start,
                                                },
                                            )
                                    `}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <CodeBlock
                                    language="typescript"
                                    code={dedent`
                                        import { OpenAI } from '@posthog/ai/openai'
                                        import { PostHog } from 'posthog-node'

                                        const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })
                                        const client = new OpenAI({ apiKey: 'your_openai_api_key', posthog })

                                        const sessionId = 'conversation-abc' // same across every turn of the conversation
                                        const traceId = crypto.randomUUID()  // one per turn
                                        const distinctId = 'user_123'

                                        // tools and getWeather() are your existing tool-calling setup
                                        const response = await client.chat.completions.create({
                                          model: 'gpt-4o-mini',
                                          messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                          tools,
                                          posthogDistinctId: distinctId,
                                          posthogTraceId: traceId,
                                          posthogProperties: { $ai_session_id: sessionId },
                                        })

                                        // Capture each tool call as a span nested under the generation above
                                        for (const call of response.choices[0].message.tool_calls ?? []) {
                                          const start = Date.now()
                                          const result = await getWeather(JSON.parse(call.function.arguments))

                                          posthog.capture({
                                            distinctId,
                                            event: '$ai_span',
                                            properties: {
                                              $ai_trace_id: traceId,             // ties the span to the generation
                                              $ai_session_id: sessionId,         // ties it to the conversation
                                              $ai_span_id: crypto.randomUUID(),
                                              $ai_span_name: call.function.name,
                                              $ai_input_state: call.function.arguments,
                                              $ai_output_state: result,
                                              $ai_latency: (Date.now() - start) / 1000,
                                            },
                                          })
                                        }
                                    `}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>

                    <Markdown>
                        See [spans](https://posthog.com/docs/ai-observability/spans) for the full list of span
                        properties.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Event properties',
            content: (
                <>
                    <Markdown>
                        Each event type has specific properties. See the tabs below for detailed property documentation
                        for each event type.
                    </Markdown>

                    <Tab.Group tabs={['Generation', 'Trace', 'Span', 'Embedding']}>
                        <Tab.List>
                            <Tab>Generation</Tab>
                            <Tab>Trace</Tab>
                            <Tab>Span</Tab>
                            <Tab>Embedding</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>{GenerationEvent && <GenerationEvent />}</Tab.Panel>
                            <Tab.Panel>{TraceEvent && <TraceEvent />}</Tab.Panel>
                            <Tab.Panel>{SpanEvent && <SpanEvent />}</Tab.Panel>
                            <Tab.Panel>{EmbeddingEvent && <EmbeddingEvent />}</Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
    ]
}

export const ManualInstallation = createInstallation(getManualSteps)

import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ManualInstallation = (): JSX.Element => {
    const { Markdown, Tab, CodeBlock, snippets, dedent } = useMDXComponents()

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

    return (
        <>
            <Markdown>
                If you're using a different server-side SDK or prefer to use the API, you can manually capture the data
                by calling the `capture` method or using the [capture API](https://posthog.com/docs/api/capture).
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

                                                const client = new PostHog('<ph_project_api_key>', {
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
                                                        $ai_model: 'gpt-4o-mini',
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

                                                posthog = Posthog("<ph_project_api_key>", host="<ph_client_api_host>")
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
                                                        '$ai_model': 'gpt-4o-mini',
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
                                        <CodeBlock language="bash" code="go get github.com/posthog/posthog-go" />

                                        <Markdown>### 2. Initialize PostHog</Markdown>
                                        <CodeBlock
                                            language="go"
                                            code={dedent`
                                                import "github.com/posthog/posthog-go"

                                                client, _ := posthog.NewWithConfig("<ph_project_api_key>", posthog.Config{
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
                                                        "$ai_model":           "gpt-4o-mini",
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
                                                require 'posthog-ruby'

                                                posthog = PostHog::Client.new({
                                                    api_key: '<ph_project_api_key>',
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
                                                    '$ai_model' => 'gpt-4o-mini',
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
                                        <CodeBlock language="bash" code="composer require posthog/posthog-php" />

                                        <Markdown>### 2. Initialize PostHog</Markdown>
                                        <CodeBlock
                                            language="php"
                                            code={dedent`
                                                <?php
                                                require_once __DIR__ . '/vendor/autoload.php';
                                                use PostHog\\PostHog;

                                                PostHog::init('<ph_project_api_key>', [
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
                                                        '$ai_model' => 'gpt-4o-mini',
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
                                                            "api_key": "<ph_project_api_key>",
                                                            "event": "$ai_generation",
                                                            "properties": {
                                                                "distinct_id": "user_123",
                                                                "$ai_trace_id": "trace_id_here",
                                                                "$ai_model": "gpt-4o-mini",
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

            <Markdown>
                {dedent`
                    ### Event Properties

                    Each event type has specific properties. See the tabs below for detailed property documentation for each event type.
                `}
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
    )
}

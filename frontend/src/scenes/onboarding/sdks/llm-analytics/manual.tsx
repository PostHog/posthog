import { useValues } from 'kea'
import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { SDKKey } from '~/types'

import { DocumentationLink } from './DocumentationLink'

function PropertiesInfoBanner(): JSX.Element {
    return (
        <LemonBanner type="info">
            <div>
                The <code>$ai_generation</code> event captures LLM call metadata including input/output, tokens,
                latency, and model information.{' '}
                <Link
                    to="https://posthog.com/docs/llm-analytics/manual-capture"
                    target="_blank"
                    targetBlankIcon
                    disableDocsPanel
                >
                    Learn about all available properties
                </Link>
            </div>
        </LemonBanner>
    )
}

export function LLMManualCaptureInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [language, setLanguage] = useState<SDKKey>(SDKKey.API)

    const languages = [
        { key: SDKKey.API, label: 'API', lang: Language.Bash },
        { key: SDKKey.NODE_JS, label: 'Node.js', lang: Language.JavaScript },
        { key: SDKKey.PYTHON, label: 'Python', lang: Language.Python },
        { key: SDKKey.GO, label: 'Go', lang: Language.Go },
        { key: SDKKey.RUBY, label: 'Ruby', lang: Language.Ruby },
        { key: SDKKey.PHP, label: 'PHP', lang: Language.PHP },
    ]

    return (
        <>
            <h3>Manual $ai_generation Event Capture</h3>
            <p>
                For server-side SDKs, you can manually capture LLM events using the <code>$ai_generation</code> event.
            </p>

            <LemonTabs
                activeKey={language}
                onChange={(key) => setLanguage(key as SDKKey)}
                tabs={languages.map((l) => ({ key: l.key, label: l.label }))}
            />

            {language === SDKKey.NODE_JS && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>npm install posthog-node</CodeSnippet>

                    <h3>2. Initialize PostHog</h3>
                    <CodeSnippet language={Language.JavaScript}>{`import { PostHog } from 'posthog-node'

const client = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})`}</CodeSnippet>

                    <h3>3. Capture $ai_generation Event</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.JavaScript}>{`// After your LLM call
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
        $ai_latency: 1.5
    }
})

client.shutdown()`}</CodeSnippet>
                </>
            )}

            {language === SDKKey.PYTHON && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>pip install posthog</CodeSnippet>

                    <h3>2. Initialize PostHog</h3>
                    <CodeSnippet language={Language.Python}>{`from posthog import Posthog

posthog = Posthog("${currentTeam?.api_token}", host="${apiHostOrigin()}")`}</CodeSnippet>

                    <h3>3. Capture $ai_generation Event</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.Python}>{`# After your LLM call
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
        '$ai_latency': 1.5
    }
)`}</CodeSnippet>
                </>
            )}

            {language === SDKKey.GO && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>go get github.com/posthog/posthog-go</CodeSnippet>

                    <h3>2. Initialize PostHog</h3>
                    <CodeSnippet language={Language.Go}>{`import "github.com/posthog/posthog-go"

client, _ := posthog.NewWithConfig("${currentTeam?.api_token}", posthog.Config{
    Endpoint: "${apiHostOrigin()}",
})
defer client.Close()`}</CodeSnippet>

                    <h3>3. Capture $ai_generation Event</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.Go}>{`// After your LLM call
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
    },
})`}</CodeSnippet>
                </>
            )}

            {language === SDKKey.RUBY && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>gem install posthog-ruby</CodeSnippet>

                    <h3>2. Initialize PostHog</h3>
                    <CodeSnippet language={Language.Ruby}>{`require 'posthog-ruby'

posthog = PostHog::Client.new({
  api_key: '${currentTeam?.api_token}',
  host: '${apiHostOrigin()}'
})`}</CodeSnippet>

                    <h3>3. Capture $ai_generation Event</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.Ruby}>{`# After your LLM call
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
  }
})`}</CodeSnippet>
                </>
            )}

            {language === SDKKey.PHP && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>composer require posthog/posthog-php</CodeSnippet>

                    <h3>2. Initialize PostHog</h3>
                    <CodeSnippet language={Language.PHP}>{`<?php
require_once __DIR__ . '/vendor/autoload.php';
use PostHog\\PostHog;

PostHog::init('${currentTeam?.api_token}', [
    'host' => '${apiHostOrigin()}'
]);`}</CodeSnippet>

                    <h3>3. Capture $ai_generation Event</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.PHP}>{`// After your LLM call
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
    ]
]);`}</CodeSnippet>
                </>
            )}

            {language === SDKKey.API && (
                <>
                    <h3>Capture via API</h3>

                    <PropertiesInfoBanner />

                    <CodeSnippet language={Language.Bash}>{`curl -X POST "${apiHostOrigin()}/i/v0/e/" \\
     -H "Content-Type: application/json" \\
     -d '{
         "api_key": "${currentTeam?.api_token}",
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
             "$ai_latency": 1.5
         }
     }'`}</CodeSnippet>
                </>
            )}

            <DocumentationLink path="llm-analytics/manual-capture" text="View full manual capture documentation ↗" />
        </>
    )
}

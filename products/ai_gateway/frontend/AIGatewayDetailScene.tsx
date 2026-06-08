import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport, SceneParams } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayDetailLogic, AIGatewayDetailLogicProps, EndpointTab } from './aiGatewayDetailLogic'
import { GatewayCredentials } from './GatewayCredentials'
import { UsageTiles } from './gatewayUsage'
import { GatewayApi } from './generated/api.schemas'

export const scene: SceneExport<AIGatewayDetailLogicProps> = {
    component: AIGatewayDetailScene,
    logic: aiGatewayDetailLogic,
    paramsToProps: ({ params: { slug } }: SceneParams): AIGatewayDetailLogicProps => ({ slug: slug ?? '' }),
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayDetailScene(): JSX.Element {
    const { gateway, gatewayLoading, detailTab } = useValues(aiGatewayDetailLogic)
    const { setDetailTab } = useActions(aiGatewayDetailLogic)

    if (gatewayLoading && !gateway) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    if (!gateway) {
        return (
            <NotFound
                object="gateway"
                caption={
                    <>
                        This gateway may have been deleted or renamed.{' '}
                        <Link to={urls.aiGateway()}>Back to AI gateway</Link>
                    </>
                }
            />
        )
    }

    return (
        <SceneContent>
            <LemonButton size="small" type="tertiary" to={urls.aiGateway()} icon={<IconArrowLeft />}>
                All gateways
            </LemonButton>
            <SceneTitleSection
                name={gateway.slug}
                description="Monitor this gateway's usage, see how to connect to it, and manage the keys that attribute to it."
                resourceType={{ type: 'llm_analytics' }}
            />

            <LemonTabs
                activeKey={detailTab}
                onChange={setDetailTab}
                tabs={[
                    { key: 'usage', label: 'Usage', content: <UsageTab gateway={gateway} /> },
                    { key: 'connect', label: 'Connect', content: <GatewayEndpoint gateway={gateway} /> },
                    { key: 'keys', label: 'Keys', content: <KeysTab gateway={gateway} /> },
                ]}
            />
        </SceneContent>
    )
}

function UsageTab({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { usage, usageLoading } = useValues(aiGatewayDetailLogic)

    return (
        <div className="flex flex-col gap-4">
            <UsageTiles usage={usage} loading={usageLoading} />
            <section className="flex flex-col gap-2">
                <h3 className="m-0">By model · last 30 days</h3>
                <Query query={byModelQuery(gateway)} readOnly />
            </section>
        </div>
    )
}

function KeysTab({ gateway }: { gateway: GatewayApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <p className="text-secondary m-0">
                Keys assigned to this gateway. A key belongs to exactly one gateway — add a second to rotate, then
                remove the old one.
            </p>
            <div className="border rounded">
                <GatewayCredentials gateway={gateway} />
            </div>
        </div>
    )
}

function GatewayEndpoint({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { endpointTab } = useValues(aiGatewayDetailLogic)
    const { setEndpointTab } = useActions(aiGatewayDetailLogic)

    if (!preflight?.ai_gateway_url) {
        return (
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Endpoint</h3>
                <p className="text-secondary m-0">
                    Set <code>AI_GATEWAY_PUBLIC_URL</code> to show this gateway's endpoint and code examples.
                </p>
            </section>
        )
    }

    // Dispatch is namespaced by slug as a path prefix: <host>/g/<slug>/v1/<shape> (ai-gateway #80).
    // Stock SDKs reach it with just a base-URL change — Anthropic appends "/v1/messages" to the gateway
    // base, OpenAI appends "chat/completions" to the base + "/v1".
    const gatewayBase = `${preflight.ai_gateway_url.replace(/\/$/, '')}/g/${gateway.slug}`
    const key = '<phx_ personal API key assigned to this gateway>'

    // Each language shows both supported shapes (OpenAI and Anthropic SDKs); cURL last.
    const tabs: Record<EndpointTab, JSX.Element> = {
        typescript: (
            <SdkExamples
                language={Language.TypeScript}
                openai={`import OpenAI from 'openai'

const client = new OpenAI({
    baseURL: '${gatewayBase}/v1', // SDK appends "chat/completions"
    apiKey: '${key}',
})
await client.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: 'Hello' }],
})`}
                anthropic={`import Anthropic from '@anthropic-ai/sdk'

const client = new Anthropic({
    baseURL: '${gatewayBase}', // SDK appends "/v1/messages"
    authToken: '${key}', // sets the Bearer header
})
await client.messages.create({
    model: 'claude-sonnet-4.6',
    max_tokens: 512,
    messages: [{ role: 'user', content: 'Hello' }],
})`}
            />
        ),
        python: (
            <SdkExamples
                language={Language.Python}
                openai={`from openai import OpenAI

client = OpenAI(
    base_url="${gatewayBase}/v1",  # SDK appends "chat/completions"
    api_key="${key}",
)
client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)`}
                anthropic={`from anthropic import Anthropic

client = Anthropic(
    base_url="${gatewayBase}",  # SDK appends "/v1/messages"
    auth_token="${key}",  # sets the Bearer header
)
client.messages.create(
    model="claude-sonnet-4.6",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello"}],
)`}
            />
        ),
        curl: (
            <CodeSnippet language={Language.Bash}>
                {`curl ${gatewayBase}/v1/messages \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-sonnet-4.6",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "Hello"}]
  }'`}
            </CodeSnippet>
        ),
    }

    return (
        <section className="flex flex-col gap-2">
            <p className="text-secondary m-0">
                Point any OpenAI- or Anthropic-shaped client at this gateway's base URL and authenticate with a key
                assigned to it. The slug rides the path, so each SDK reaches the gateway with only a base-URL change.
            </p>
            <CodeSnippet language={Language.Bash}>{gatewayBase}</CodeSnippet>
            <LemonTabs
                activeKey={endpointTab}
                onChange={setEndpointTab}
                tabs={[
                    { key: 'typescript', label: 'TypeScript' },
                    { key: 'python', label: 'Python' },
                    { key: 'curl', label: 'cURL' },
                ]}
            />
            {tabs[endpointTab]}
        </section>
    )
}

// Both supported request shapes for one language: the OpenAI SDK (base + /v1) and
// the Anthropic SDK (base only — it appends /v1/messages itself).
function SdkExamples({
    language,
    openai,
    anthropic,
}: {
    language: Language
    openai: string
    anthropic: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <span className="text-secondary text-xs font-semibold uppercase">OpenAI SDK</span>
                <CodeSnippet language={language}>{openai}</CodeSnippet>
            </div>
            <div className="flex flex-col gap-1">
                <span className="text-secondary text-xs font-semibold uppercase">Anthropic SDK</span>
                <CodeSnippet language={language}>{anthropic}</CodeSnippet>
            </div>
        </div>
    )
}

function byModelQuery(gateway: GatewayApi): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: `
                SELECT
                    properties.$ai_model AS model,
                    count() AS requests,
                    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
                    sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
                    sum(toFloat(properties.$ai_output_tokens)) AS output_tokens
                FROM events
                WHERE event = '$ai_generation'
                    AND properties.$ai_gateway_slug = {slug}
                    AND timestamp >= now() - INTERVAL 30 DAY
                GROUP BY model
                ORDER BY cost_usd DESC
            `,
            values: { slug: gateway.slug },
        },
    }
}

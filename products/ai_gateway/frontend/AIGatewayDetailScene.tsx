import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
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
    paramsToProps: ({ params: { id } }: SceneParams): AIGatewayDetailLogicProps => ({ id: id ?? '' }),
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayDetailScene(): JSX.Element {
    const { gateway, gatewayLoading } = useValues(aiGatewayDetailLogic)

    if (gatewayLoading && !gateway) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    if (!gateway) {
        return (
            <SceneContent>
                <p>Gateway not found.</p>
                <LemonButton type="secondary" to={urls.aiGateway()} icon={<IconArrowLeft />}>
                    Back to gateways
                </LemonButton>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <LemonButton size="small" type="tertiary" to={urls.aiGateway()} icon={<IconArrowLeft />}>
                All gateways
            </LemonButton>
            <SceneTitleSection
                name={gateway.slug}
                description="Usage and keys for this gateway. A request is attributed to this gateway by using one of its keys; the gateway slug in the endpoint path mirrors that binding so calling code reads clearly."
                resourceType={{ type: 'llm_analytics' }}
            />

            <GatewayEndpoint gateway={gateway} />

            <UsagePanel />

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Usage by model · last 30 days</h3>
                <Query query={byModelQuery(gateway)} readOnly />
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Keys</h3>
                <p className="text-secondary m-0">
                    Keys assigned to this gateway. A key belongs to exactly one gateway — add a second to rotate, then
                    remove the old one.
                </p>
                <div className="border rounded">
                    <GatewayCredentials gateway={gateway} />
                </div>
            </section>
        </SceneContent>
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

    const snippets: Record<EndpointTab, { language: Language; code: string }> = {
        curl: {
            language: Language.Bash,
            code: `curl ${gatewayBase}/v1/messages \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-sonnet-4.6",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
        },
        openai: {
            language: Language.Python,
            code: `from openai import OpenAI

client = OpenAI(
    base_url="${gatewayBase}/v1",  # SDK appends "chat/completions"
    api_key="<phx_ personal API key assigned to this gateway>",
)
client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)`,
        },
        anthropic: {
            language: Language.Python,
            code: `from anthropic import Anthropic

client = Anthropic(
    base_url="${gatewayBase}",  # SDK appends "/v1/messages"
    auth_token="<phx_ personal API key assigned to this gateway>",  # sets the Bearer header
)
client.messages.create(
    model="claude-sonnet-4.6",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello"}],
)`,
        },
    }

    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0">Endpoint</h3>
            <p className="text-secondary m-0">
                Point any OpenAI- or Anthropic-shaped client at this gateway's base URL and authenticate with a key
                assigned to it. The slug rides the path, so each SDK reaches the gateway with only a base-URL change.
            </p>
            <CodeSnippet language={Language.Bash}>{gatewayBase}</CodeSnippet>
            <LemonTabs
                activeKey={endpointTab}
                onChange={setEndpointTab}
                tabs={[
                    { key: 'curl', label: 'cURL' },
                    { key: 'openai', label: 'OpenAI' },
                    { key: 'anthropic', label: 'Anthropic' },
                ]}
            />
            <CodeSnippet language={snippets[endpointTab].language}>{snippets[endpointTab].code}</CodeSnippet>
        </section>
    )
}

function UsagePanel(): JSX.Element {
    const { usage, usageLoading } = useValues(aiGatewayDetailLogic)

    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0">Usage · last 30 days</h3>
            <UsageTiles usage={usage} loading={usageLoading} />
        </section>
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

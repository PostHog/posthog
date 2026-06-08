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

    // OpenAI-shaped examples (the broadest compatibility); cURL last. Anthropic SDKs
    // work too — see the note below. The slug rides the path, so it's a base-URL change.
    const tabs: { key: EndpointTab; label: string; language: Language; code: string }[] = [
        {
            key: 'typescript',
            label: 'TypeScript',
            language: Language.TypeScript,
            code: `import OpenAI from 'openai'

const client = new OpenAI({
    baseURL: '${gatewayBase}/v1',
    apiKey: '${key}',
})
const response = await client.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: 'Hello' }],
})`,
        },
        {
            key: 'python',
            label: 'Python',
            language: Language.Python,
            code: `from openai import OpenAI

client = OpenAI(
    base_url="${gatewayBase}/v1",
    api_key="${key}",
)
client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)`,
        },
        {
            key: 'curl',
            label: 'cURL',
            language: Language.Bash,
            code: `curl ${gatewayBase}/v1/chat/completions \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
        },
    ]

    return (
        <section className="flex flex-col gap-2">
            <p className="text-secondary m-0">
                Point any OpenAI- or Anthropic-compatible client at this gateway's base URL and authenticate with a key
                assigned to it.
            </p>
            <CodeSnippet language={Language.Bash}>{gatewayBase}</CodeSnippet>
            <LemonTabs
                activeKey={endpointTab}
                onChange={setEndpointTab}
                tabs={tabs.map(({ key, label, language, code }) => ({
                    key,
                    label,
                    content: <CodeSnippet language={language}>{code}</CodeSnippet>,
                }))}
            />
            <p className="text-secondary text-xs m-0">
                Using the Anthropic SDK? Point its base URL at <code>{gatewayBase}</code> (it appends{' '}
                <code>/v1/messages</code> itself).
            </p>
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

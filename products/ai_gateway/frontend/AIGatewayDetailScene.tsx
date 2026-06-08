import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ComponentType } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { AnthropicLogo } from 'scenes/onboarding/sdks/logos/AnthropicLogo'
import { OpenAILogo } from 'scenes/onboarding/sdks/logos/OpenAILogo'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport, SceneParams } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayDetailLogic, AIGatewayDetailLogicProps, EndpointProvider, EndpointTab } from './aiGatewayDetailLogic'
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
    const { endpointTab, endpointProvider } = useValues(aiGatewayDetailLogic)
    const { setEndpointTab, setEndpointProvider } = useActions(aiGatewayDetailLogic)

    if (!preflight?.ai_gateway_url) {
        return (
            <section className="flex flex-col gap-2">
                <p className="text-secondary m-0">
                    Set <code>AI_GATEWAY_PUBLIC_URL</code> to show this gateway's endpoint and code examples.
                </p>
            </section>
        )
    }

    // Dispatch is namespaced by slug as a path prefix: <host>/g/<slug>/v1/<shape> (ai-gateway #80).
    // The slug rides the path, so stock SDKs reach it with only a base-URL change.
    const gatewayBase = `${preflight.ai_gateway_url.replace(/\/$/, '')}/g/${gateway.slug}`
    const key = '<phx_ personal API key assigned to this gateway>'

    // provider → language → snippet. The OpenAI SDK appends "chat/completions" to base + "/v1";
    // the Anthropic SDK appends "/v1/messages" to the gateway base.
    const snippets: Record<EndpointProvider, Record<EndpointTab, { language: Language; code: string }>> = {
        openai: {
            typescript: {
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
            python: {
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
            curl: {
                language: Language.Bash,
                code: `curl ${gatewayBase}/v1/chat/completions \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
            },
        },
        anthropic: {
            typescript: {
                language: Language.TypeScript,
                code: `import Anthropic from '@anthropic-ai/sdk'

const client = new Anthropic({
    baseURL: '${gatewayBase}',
    authToken: '${key}', // sets the Bearer header
})
const message = await client.messages.create({
    model: 'claude-sonnet-4.6',
    max_tokens: 512,
    messages: [{ role: 'user', content: 'Hello' }],
})`,
            },
            python: {
                language: Language.Python,
                code: `from anthropic import Anthropic

client = Anthropic(
    base_url="${gatewayBase}",
    auth_token="${key}",  # sets the Bearer header
)
client.messages.create(
    model="claude-sonnet-4.6",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello"}],
)`,
            },
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
        },
    }

    const languages: { key: EndpointTab; label: string }[] = [
        { key: 'typescript', label: 'TypeScript' },
        { key: 'python', label: 'Python' },
        { key: 'curl', label: 'cURL' },
    ]

    // The logos are white in dark mode, but the selected segment has a light
    // background — force the selected one's mark dark so it stays visible.
    const providerIcon = (provider: EndpointProvider, Logo: ComponentType): JSX.Element => (
        <span className={clsx('flex [&>svg]:size-4', endpointProvider === provider && '[&_path]:dark:fill-black')}>
            <Logo />
        </span>
    )

    return (
        <section className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="small"
                value={endpointProvider}
                onChange={setEndpointProvider}
                options={[
                    { value: 'openai', label: 'OpenAI', icon: providerIcon('openai', OpenAILogo) },
                    { value: 'anthropic', label: 'Anthropic', icon: providerIcon('anthropic', AnthropicLogo) },
                ]}
            />
            <LemonTabs
                activeKey={endpointTab}
                onChange={setEndpointTab}
                tabs={languages.map(({ key, label }) => {
                    const snippet = snippets[endpointProvider][key]
                    return {
                        key,
                        label,
                        content: <CodeSnippet language={snippet.language}>{snippet.code}</CodeSnippet>,
                    }
                })}
            />
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

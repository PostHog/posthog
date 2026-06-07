import { useValues } from 'kea'

import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'
import { SceneExport, SceneParams } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayDetailLogic, AIGatewayDetailLogicProps } from './aiGatewayDetailLogic'
import { CREATE_KEY_URL, GatewayCredentials } from './GatewayCredentials'
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
                description="Usage and credentials attributed to this gateway. The gateway is selected by the credential a request authenticates with — one key per gateway, no per-request selector."
                resourceType={{ type: 'llm_analytics' }}
            />

            <UsagePanel />

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Usage by model</h3>
                <Query query={byModelQuery(gateway)} readOnly />
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Bound credentials</h3>
                <p className="text-secondary m-0">
                    Requests authenticated with these credentials attribute their usage to this gateway.
                </p>
                <div className="border rounded">
                    <GatewayCredentials gateway={gateway} />
                </div>
            </section>

            <NextSteps />
        </SceneContent>
    )
}

function UsagePanel(): JSX.Element {
    const { usage, usageLoading } = useValues(aiGatewayDetailLogic)

    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0">Usage · last 30 days</h3>
            <div className="flex gap-2 flex-wrap">
                <UsageTile
                    label="Requests"
                    value={usage ? humanFriendlyNumber(usage.requests) : null}
                    loading={usageLoading}
                />
                <UsageTile
                    label="Tokens"
                    value={usage ? humanFriendlyNumber(usage.inputTokens + usage.outputTokens) : null}
                    loading={usageLoading}
                />
                <UsageTile label="Cost" value={usage ? `$${usage.costUsd.toFixed(2)}` : null} loading={usageLoading} />
            </div>
        </section>
    )
}

function UsageTile({ label, value, loading }: { label: string; value: string | null; loading: boolean }): JSX.Element {
    return (
        <div className="border rounded p-4 min-w-32">
            <div className="text-secondary text-xs uppercase">{label}</div>
            {loading || value === null ? (
                <LemonSkeleton className="h-7 w-16 mt-1" />
            ) : (
                <div className="text-2xl font-semibold">{value}</div>
            )}
        </div>
    )
}

function NextSteps(): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0">Next steps</h3>
            <div className="flex gap-2 flex-wrap">
                <LemonButton type="secondary" icon={<IconPlus />} to={CREATE_KEY_URL}>
                    Create personal API key
                </LemonButton>
                <LemonButton type="secondary" icon={<IconPlus />} to={urls.aiGateway()}>
                    Create another gateway
                </LemonButton>
                <LemonButton type="secondary" to={urls.settings('environment-ai-observability')}>
                    Configure providers
                </LemonButton>
            </div>
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

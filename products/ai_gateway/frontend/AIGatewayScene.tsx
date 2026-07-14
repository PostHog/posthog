import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ComponentType } from 'react'

import * as roboHogPng from '@posthog/brand/hoggies/png/robo-hog'
import { LemonSegmentedButton, LemonTabs } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { AnthropicLogo } from 'scenes/onboarding/shared/logos/AnthropicLogo'
import { OpenAILogo } from 'scenes/onboarding/shared/logos/OpenAILogo'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayLogic, EndpointProvider, EndpointTab } from './aiGatewayLogic'
import { GatewayBalanceCard, GatewayTopUpModal } from './GatewayTopUp'
import { ModelBreakdownTable, SpendChart, UsageMetrics } from './gatewayUsage'

const HedgehogRoboHog = pngHoggie(roboHogPng)

const AI_GATEWAY_DESCRIPTION =
    'One endpoint for every major LLM, billed at cost — no markup on tokens. Point your app at the gateway and ' +
    'PostHog tracks its usage, cost, and spend for you. Any project secret key with the llm_gateway:read scope ' +
    'can call it, and you can add or rotate keys anytime with no downtime.'

export const scene: SceneExport = {
    component: AIGatewayScene,
    logic: aiGatewayLogic,
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { usage, spendChart, spendSeriesLoading, modelUsage, modelUsageLoading, hasUsage } = useValues(aiGatewayLogic)

    if (!featureFlags[FEATURE_FLAGS.AI_GATEWAY]) {
        return <NotFound object="page" />
    }

    // Until the model breakdown resolves we can't tell a brand-new team from an active one, so keep showing
    // the dashboard (with skeletons) and only fall back to the intro once we know there's genuinely no usage.
    const isEmpty = !modelUsageLoading && !hasUsage

    return (
        <SceneContent>
            <SceneTitleSection
                name="AI gateway"
                description="Every major LLM through one endpoint, billed at cost."
                resourceType={{ type: 'ai_gateway' }}
            />
            {isEmpty ? (
                <GatewayIntro />
            ) : (
                <>
                    <SceneSection title="Usage" description="Last 30 days" titleSize="sm">
                        <div className="flex gap-2 flex-wrap">
                            <UsageMetrics usage={usage} loading={modelUsageLoading} />
                            <GatewayBalanceCard />
                        </div>
                        <SpendChart data={spendChart.data} labels={spendChart.labels} loading={spendSeriesLoading} />
                    </SceneSection>
                    <SceneSection
                        title="By model"
                        description="Spend and tokens per model, last 30 days"
                        titleSize="sm"
                    >
                        <ModelBreakdownTable rows={modelUsage} loading={modelUsageLoading} />
                    </SceneSection>
                </>
            )}
            <SceneSection
                title="Connect your app"
                titleSize="sm"
                description={
                    <>
                        Every request is tracked in <Link to={urls.aiObservabilityDashboard()}>AI observability</Link>{' '}
                        with no SDK instrumentation needed. Already sending generations through a PostHog LLM SDK?
                        Switch back to the official provider packages so each one is counted once.
                    </>
                }
            >
                <GatewayEndpoint />
            </SceneSection>
            {!isEmpty && <GatewayTopUpModal />}
        </SceneContent>
    )
}

// Shown until a team sends its first request, where the zeroed-out dashboard would otherwise read as broken.
function GatewayIntro(): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-6 rounded flex items-center gap-6">
            <HedgehogRoboHog className="w-32 hidden md:block shrink-0" />
            <div className="flex-shrink">
                <h3 className="m-0">No gateway usage yet</h3>
                <p className="ml-0 mt-1 mb-0 text-secondary">{AI_GATEWAY_DESCRIPTION}</p>
            </div>
        </div>
    )
}

function GatewayEndpoint(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { endpointTab, endpointProvider } = useValues(aiGatewayLogic)
    const { setEndpointTab, setEndpointProvider } = useActions(aiGatewayLogic)

    if (!preflight?.ai_gateway_url) {
        return (
            <p className="text-secondary m-0">
                Set <code>AI_GATEWAY_PUBLIC_URL</code> to show the gateway's endpoint and code examples.
            </p>
        )
    }

    const gatewayBase = preflight.ai_gateway_url.replace(/\/$/, '')
    const key = '<your phs_… project secret key with the llm_gateway:read scope>'

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
    model: 'gpt-5-mini',
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
    model="gpt-5-mini",
    messages=[{"role": "user", "content": "Hello"}],
)`,
            },
            curl: {
                language: Language.Bash,
                code: `curl ${gatewayBase}/v1/chat/completions \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-5-mini",
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
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_KEY" \\
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
        <div className="flex flex-col gap-2">
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
                tabs={languages.map(({ key: langKey, label }) => {
                    const snippet = snippets[endpointProvider][langKey]
                    return {
                        key: langKey,
                        label,
                        content: <CodeSnippet language={snippet.language}>{snippet.code}</CodeSnippet>,
                    }
                })}
            />
        </div>
    )
}

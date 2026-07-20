import { Meta } from '@storybook/react'

import * as xRayHogPng from '@posthog/brand/hoggies/png/x-ray'
import { IconGraph } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductEmptyState } from './ProductEmptyState'
import type { ProductEmptyStateConfig, ProductEmptyStateMode } from './types'

const HedgehogXRay = pngHoggie(xRayHogPng)

function DemoPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const rows = [
        { name: 'search_docs()', meta: 'claude-agent · ok', latency: '142ms', ok: true },
        { name: 'run_query()', meta: 'claude-agent · ok', latency: '88ms', ok: true },
        { name: 'create_issue()', meta: 'cursor · failed', latency: 'err', ok: false },
        { name: 'list_flags()', meta: 'claude-agent · ok', latency: '53ms', ok: true },
    ]

    return (
        <div className="rounded border border-primary bg-surface-primary overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-primary text-xs font-semibold">
                <span>Tool calls</span>
                <LemonTag size="small">{mode === 'waiting-for-data' ? 'listening…' : 'live'}</LemonTag>
            </div>
            {rows.map((row) => (
                <div
                    key={row.name}
                    className="flex items-center gap-2 px-3 py-2 border-b border-primary last:border-b-0"
                >
                    <div className="flex-1 min-w-0">
                        <div className="font-mono text-xs">{row.name}</div>
                        <div className="text-xs text-secondary">{row.meta}</div>
                    </div>
                    <LemonTag size="small" type={row.ok ? 'default' : 'danger'}>
                        {row.latency}
                    </LemonTag>
                </div>
            ))}
        </div>
    )
}

const demoConfig: ProductEmptyStateConfig = {
    productKey: ProductKey.MCP_ANALYTICS,
    productName: 'MCP analytics',
    icon: <IconGraph />,
    accentColor: 'var(--color-product-llm-analytics-light)',
    hedgehog: HedgehogXRay,
    copy: {
        'needs-setup': {
            headline: 'Know how agents actually use your tools',
            lead: 'Every MCP tool call, argument and result, so you can see which tools agents reach for, where they fail, and how long each call takes.',
            hint: 'Fastest way in: our wizard wires up the SDK for you.',
        },
        'waiting-for-data': {
            headline: "You're connected. Now make a tool call",
            lead: 'Events land here the moment an agent calls one of your tools.',
        },
    },
    wizard: { slug: 'mcp-analytics' },
    docsUrl: 'https://posthog.com/docs/mcp-analytics',
    previewLabel: "What you'll capture, once connected",
    Preview: DemoPreview,
}

const meta: Meta<typeof ProductEmptyState> = {
    title: 'Components/Product Empty State/Product Setup',
    component: ProductEmptyState,
}
export default meta

export function NeedsSetup(): JSX.Element {
    return <ProductEmptyState config={demoConfig} mode="needs-setup" />
}

export function WaitingForData(): JSX.Element {
    return <ProductEmptyState config={demoConfig} mode="waiting-for-data" />
}

export function WithoutWizardSelfHosted(): JSX.Element {
    return <ProductEmptyState config={{ ...demoConfig, wizard: undefined }} mode="needs-setup" />
}

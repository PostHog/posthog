import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { ContextWarehouseAppShell } from './ContextWarehouseAppShell'
import { ContextWarehouseChangeRequest } from './ContextWarehouseChangeRequest'
import { ContextWarehouseFindings } from './ContextWarehouseFindings'
import { ContextWarehouseHandoff } from './ContextWarehouseHandoff'
import { ContextWarehouseHome } from './ContextWarehouseHome'
import { ContextWarehouseScene } from './ContextWarehouseScene'
import { type ContextWarehouseSection } from './ContextWarehouseSidebar'
import { ContextWarehouseSqlWorkspace } from './ContextWarehouseSqlWorkspace'

const HEALTH_CARDS = [
    {
        title: 'Sources',
        value: '5 healthy',
        description: '1 source needs attention',
        status: 'warning' as const,
    },
    {
        title: 'Models',
        value: '18 healthy',
        description: '2 need attention',
        status: 'warning' as const,
    },
    {
        title: 'Quality checks',
        value: '42 of 44 passing',
        description: '2 failed on the latest run',
        status: 'warning' as const,
    },
    {
        title: 'Freshness',
        value: '15 of 18 on target',
        description: '3 models are delayed',
        status: 'warning' as const,
    },
]

const ATTENTION_ITEMS = [
    {
        title: 'Stripe subscription sync failed',
        description: 'The subscriptions table did not update during the latest scheduled sync.',
        source: 'Stripe',
        actionLabel: 'Open in Inbox',
    },
    {
        title: 'revenue_by_customer is late',
        description: 'The model missed its freshness target by 47 minutes. Downstream revenue data may be stale.',
        source: 'Data model',
        actionLabel: 'Open in Inbox',
    },
    {
        title: 'Two relationship proposals need review',
        description: 'The data catalog found two joins that need an owner to confirm their keys.',
        source: 'Data catalog',
        actionLabel: 'Open in Inbox',
    },
]

const QUERY_RESULTS = [
    { billingInterval: 'Monthly', revenue: '$124,820', change: '-6.3%' },
    { billingInterval: 'Annual', revenue: '$412,560', change: '-18.4%' },
]

const INITIAL_QUERY = `SELECT
    plan_interval,
    revenue,
    round(100 * (revenue - previous_revenue) / nullIf(previous_revenue, 0), 1) AS seven_day_change
FROM (
    SELECT
        plan_interval,
        sumIf(revenue, day >= today() - 7) AS revenue,
        sumIf(revenue, day < today() - 7) AS previous_revenue
    FROM revenue_by_customer
    WHERE day >= today() - 14
    GROUP BY plan_interval
)
ORDER BY revenue DESC`

const ORIGINAL_QUERY = `SELECT
    customer_id,
    sum(revenue) AS revenue
FROM revenue_by_customer
WHERE day >= today() - 7
GROUP BY customer_id`

const PROPOSED_QUERY = `SELECT
    customer_id,
    plan_interval,
    sum(revenue) AS revenue
FROM revenue_by_customer
WHERE day >= today() - 7
GROUP BY customer_id, plan_interval`

const HANDOFF_CONTENT: Record<
    Exclude<ContextWarehouseSection, 'home' | 'sql' | 'findings'>,
    { title: string; description: string; details: string[] }
> = {
    notebooks: {
        title: 'Notebooks',
        description: 'Explore warehouse data and document an analysis with live queries, charts, and commentary.',
        details: ['SQL and HogQL blocks', 'Charts and commentary', 'Shared analysis'],
    },
    sources: {
        title: 'Data sources',
        description: 'Connect imports and inspect the health of every synced schema.',
        details: ['Source setup and credentials', 'Schema sync configuration', 'Recent runs and failures'],
    },
    models: {
        title: 'Data models',
        description: 'Build reusable views and inspect their lineage, schedules, and freshness.',
        details: ['Saved queries and views', 'Materialization schedules', 'Dependencies and lineage'],
    },
    catalog: {
        title: 'Data catalog',
        description: 'Review metrics, certifications, and table relationships in one governed catalog.',
        details: ['Canonical metrics', 'Certified tables and views', 'Relationship proposals'],
    },
    'batch-exports': {
        title: 'Batch exports',
        description: 'Send PostHog data to external storage on a schedule.',
        details: ['Export destinations', 'Schedules and filters', 'Run history'],
    },
    monitoring: {
        title: 'Monitoring',
        description: 'Track cost, usage, query performance, freshness, and failed jobs in one place.',
        details: ['Cost and usage', 'Query performance', 'Jobs and freshness'],
    },
    compute: {
        title: 'Compute',
        description: 'Manage the compute engine and connect external tools to the PostHog warehouse.',
        details: ['Connection details', 'Workload capacity', 'Engine settings'],
    },
}

type HarnessView = ContextWarehouseSection | 'change-request'
type PreviewDecision = 'pending' | 'changes-requested' | 'approved'

function ContextWarehouseStoryHarness({ initialView }: { initialView: HarnessView }): JSX.Element {
    const [view, setView] = useState<HarnessView>(initialView)
    const [query, setQuery] = useState(INITIAL_QUERY)
    const [composerValue, setComposerValue] = useState('')
    const [reviewerNote, setReviewerNote] = useState('Please confirm whether refunds stay grouped correctly.')
    const [decision, setDecision] = useState<PreviewDecision>('pending')
    const [lastAction, setLastAction] = useState<string | null>(null)

    const activeSection: ContextWarehouseSection = view === 'change-request' ? 'models' : view

    const navigate = (section: ContextWarehouseSection): void => {
        setView(section)
        setLastAction(null)
    }

    let content: JSX.Element
    if (view === 'home') {
        content = (
            <ContextWarehouseHome
                attentionItems={ATTENTION_ITEMS}
                healthCards={HEALTH_CARDS}
                onAttentionAction={(item) => setLastAction(`${item.actionLabel}: ${item.title}`)}
                onOpenSqlEditor={() => navigate('sql')}
            />
        )
    } else if (view === 'sql') {
        content = (
            <ContextWarehouseSqlWorkspace
                composerValue={composerValue}
                onComposerChange={setComposerValue}
                onComposerSubmit={() => {
                    setLastAction('AI message sent in preview')
                    setComposerValue('')
                }}
                onQueryChange={setQuery}
                onRun={() => setLastAction('Query run in preview')}
                query={query}
                results={QUERY_RESULTS}
            />
        )
    } else if (view === 'findings') {
        content = (
            <ContextWarehouseFindings
                findings={ATTENTION_ITEMS}
                onOpenInbox={(finding) => setLastAction(`Open in Inbox: ${finding.title}`)}
            />
        )
    } else if (view === 'change-request') {
        content = (
            <ContextWarehouseChangeRequest
                decision={decision}
                onDecisionChange={setDecision}
                onReviewerNoteChange={setReviewerNote}
                originalQuery={ORIGINAL_QUERY}
                proposedQuery={PROPOSED_QUERY}
                reason="Revenue reporting needs a stable billing interval dimension before customer totals are aggregated."
                reviewerNote={reviewerNote}
                summary="Add plan_interval to revenue_by_customer output and grouping."
                validationItems={['Query compiles', 'Preview returned 24 rows', 'Output changes: adds plan_interval']}
            />
        )
    } else {
        const handoff = HANDOFF_CONTENT[view]
        content = (
            <ContextWarehouseHandoff
                description={handoff.description}
                details={handoff.details}
                title={handoff.title}
            />
        )
    }

    return (
        <ContextWarehouseAppShell
            activeSection={activeSection}
            findingCount={ATTENTION_ITEMS.length}
            onSectionChange={navigate}
        >
            <ContextWarehouseScene>
                <div className="space-y-3">
                    {lastAction ? (
                        <LemonBanner type="success" data-attr="context-warehouse-story-action">
                            {lastAction}. No production data changed.
                        </LemonBanner>
                    ) : null}
                    {content}
                </div>
            </ContextWarehouseScene>
        </ContextWarehouseAppShell>
    )
}

const meta: Meta = {
    title: 'Products/Data warehouse/Context warehouse prototype',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            includeNavigationInSnapshot: true,
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

type Story = StoryObj<typeof meta>

export const Home: Story = {
    render: () => <ContextWarehouseStoryHarness initialView="home" />,
    parameters: { testOptions: { viewportWidths: ['wide', 'superwide'] } },
}

export const SqlWorkspace: Story = {
    render: () => <ContextWarehouseStoryHarness initialView="sql" />,
    parameters: {
        testOptions: {
            viewportWidths: ['wide', 'superwide'],
            waitForSelector: '.monaco-editor',
        },
    },
}

export const Notebooks: Story = {
    render: () => <ContextWarehouseStoryHarness initialView="notebooks" />,
    parameters: { testOptions: { viewportWidths: ['wide'] } },
}

export const ScopedFindings: Story = {
    render: () => <ContextWarehouseStoryHarness initialView="findings" />,
    parameters: { testOptions: { viewportWidths: ['wide', 'superwide'] } },
}

export const ChangeRequestConcept: Story = {
    render: () => <ContextWarehouseStoryHarness initialView="change-request" />,
    parameters: {
        testOptions: {
            viewportWidths: ['wide', 'superwide'],
            waitForSelector: '.monaco-editor',
        },
    },
}

// SCRATCH: design exploration for telling views and materialized views apart in the SQL editor sidebar.
// Not meant to be committed. Delete once an option is picked.
import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    IconCalculator,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconDocument,
    IconPauseFilled,
    IconRefresh,
    IconXCircle,
} from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { IconTextSize } from 'lib/lemon-ui/icons'
import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

type Kind = 'view' | 'matview'
type Status = 'ok' | 'paused' | 'failed'

interface Sample {
    name: string
    kind: Kind
    status?: Status
    /** Expanded rows show their columns, as in the real sidebar */
    expanded?: boolean
}

// Invented names with a long shared prefix, where the end is what tells them apart
const SAMPLES: Sample[] = [
    { name: 'orders_by_day', kind: 'view' },
    { name: 'shop_fulfilment_queue_cost', kind: 'view', expanded: true },
    { name: 'shop_fulfilment_queue_share_monthly', kind: 'matview', expanded: true },
    { name: 'shop_dash_region_monthly_orders', kind: 'matview' },
    { name: 'shop_dash_region_monthly_refunds', kind: 'matview', status: 'paused' },
    { name: 'shop_dash_storefront_weekly_active', kind: 'matview', status: 'failed' },
    { name: 'shop_returns_unit_economics_monthly', kind: 'view' },
    { name: 'carts', kind: 'matview' },
]

const COLUMNS = [
    { name: 'order_count', type: 'integer' },
    { name: 'region', type: 'string' },
]

const KIND_LABEL: Record<Kind, string> = { view: 'View', matview: 'Materialized view' }

// ---------- shared pieces ----------

function StatusGlyph({ status }: { status?: Status }): JSX.Element | null {
    if (status === 'paused') {
        return (
            <Tooltip title="Scheduled runs are suspended">
                <IconPauseFilled className="shrink-0 text-warning" />
            </Tooltip>
        )
    }
    if (status === 'failed') {
        return (
            <Tooltip title="The last materialization run failed">
                <IconXCircle className="shrink-0 text-danger" />
            </Tooltip>
        )
    }
    return null
}

function ColumnRow({ name, type }: { name: string; type: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2">
            <span className="truncate font-mono text-xs">{name}</span>
            <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">{type}</span>
        </div>
    )
}

function columnNodes(parentId: string): TreeDataItem[] {
    return COLUMNS.map((c) => ({
        id: `${parentId}-${c.name}`,
        name: c.name,
        icon:
            c.type === 'string' ? (
                <IconTextSize className="text-sky-500" />
            ) : (
                <IconCalculator className="text-emerald-500" />
            ),
        record: { type: 'column', column: c },
    }))
}

interface RowOptions {
    icon: (s: Sample) => JSX.Element
    /** Content after the name, inside the name's flex row. */
    afterName?: (s: Sample) => JSX.Element | null
    /** Replaces the plain name, for example to truncate in the middle. */
    renderName?: (s: Sample) => JSX.Element
    tooltip?: (s: Sample) => JSX.Element | undefined
}

function buildTree(samples: Sample[], opts: RowOptions): TreeDataItem[] {
    return samples.map((s) => ({
        id: s.name,
        name: s.name,
        icon: opts.icon(s),
        record: { type: 'view', sample: s },
        children: columnNodes(s.name),
    }))
}

function Tree({
    samples = SAMPLES,
    opts,
    width,
}: {
    samples?: Sample[]
    opts: RowOptions
    width: number
}): JSX.Element {
    const [expanded, setExpanded] = useState<string[]>(samples.filter((s) => s.expanded).map((s) => s.name))
    return (
        <div
            className="border rounded bg-surface-primary p-1 [--lemon-tree-button-height:30px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width }}
        >
            <LemonTree
                data={buildTree(samples, opts)}
                expandedItemIds={expanded}
                onSetExpandedItemIds={setExpanded}
                selectMode="all"
                defaultNodeIcon={<IconChevronRight />}
                renderItemTooltip={(item) => (item.record?.sample ? opts.tooltip?.(item.record.sample) : undefined)}
                renderItem={(item, children) => {
                    if (item.record?.type === 'column') {
                        return <ColumnRow {...item.record.column} />
                    }
                    const s: Sample = item.record?.sample
                    if (!s) {
                        return children
                    }
                    return (
                        <div className="flex min-w-0 items-center gap-1.5">
                            {opts.renderName ? opts.renderName(s) : <span className="truncate">{s.name}</span>}
                            {opts.afterName?.(s)}
                        </div>
                    )
                }}
            />
        </div>
    )
}

/** Each option is shown at the default sidebar width (300px) and at a narrow one. */
function Frame({
    title,
    notes,
    opts,
    samples,
}: {
    title: string
    notes: string
    opts: RowOptions
    samples?: Sample[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 p-4 max-w-[760px]">
            <div>
                <h3 className="mb-1">{title}</h3>
                <p className="text-secondary text-sm m-0">{notes}</p>
            </div>
            <div className="flex gap-6 items-start">
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-tertiary">Default width (300px)</span>
                    <Tree opts={opts} width={300} samples={samples} />
                </div>
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-tertiary">Narrow (220px)</span>
                    <Tree opts={opts} width={220} samples={samples} />
                </div>
            </div>
        </div>
    )
}

// ---------- the options ----------

const meta: Meta = {
    title: 'Scratch/SQL editor sidebar/View kinds',
    parameters: { layout: 'padded', testOptions: { waitForSelector: '[role=treeitem]' } },
}
export default meta
type Story = StoryObj

/** What ships today: a text label per row. The label never shrinks, so the name loses the space. */
export const Current: Story = {
    render: () => (
        <Frame
            title="Today"
            notes="The kind label is a non-shrinking flex item, so long names are ellipsised first. In the app the label also hides below 14rem, so very narrow trees give no hint at all (not simulated here)."
            opts={{
                icon: (s) => (s.kind === 'matview' ? <IconDatabase /> : <IconDocument />),
                renderName: (s) => (
                    <>
                        <span className="truncate min-w-0">{s.name}</span>
                    </>
                ),
                afterName: (s) => (
                    <>
                        <StatusGlyph status={s.status} />
                        <span className="rounded px-1.5 py-0.5 text-xs text-muted-alt whitespace-nowrap">
                            {s.kind === 'matview' ? 'materialized view' : 'view'}
                        </span>
                    </>
                ),
            }}
        />
    ),
}

/** A: keep the glyphs, but make the materialized one visibly different: filled, tinted chip vs a plain outline. */
export const A_TintedChipIcon: Story = {
    render: () => (
        <Frame
            title="A. Tinted chip for materialized"
            notes="Views keep the plain document glyph. Materialized views get a filled sky-blue chip with the database glyph, so the two read differently even at a glance and in peripheral vision. No label."
            opts={{
                icon: (s) =>
                    s.kind === 'matview' ? (
                        <span className="flex size-5 shrink-0 items-center justify-center rounded bg-sky-500/15 text-sky-500 [&_svg]:size-3.5">
                            <IconDatabase />
                        </span>
                    ) : (
                        <span className="flex size-5 shrink-0 items-center justify-center text-tertiary">
                            <IconDocument />
                        </span>
                    ),
                afterName: (s) => <StatusGlyph status={s.status} />,
            }}
        />
    ),
}

/** B: same base glyph (both are "a saved query"), materialized adds a small storage badge on the corner. */
export const B_CornerBadge: Story = {
    render: () => (
        <Frame
            title="B. Same glyph, storage badge on materialized"
            notes="Both kinds are a document, because both are a saved query. A materialized view gets a small database badge on the bottom-right corner, meaning 'this one is stored'. The status glyph still sits after the name."
            opts={{
                icon: (s) => (
                    <span className="relative flex size-5 shrink-0 items-center justify-center">
                        <IconDocument className={s.kind === 'matview' ? 'text-sky-500' : 'text-tertiary'} />
                        {s.kind === 'matview' ? (
                            <span className="absolute -bottom-0.5 right-0 flex size-3 items-center justify-center rounded-full bg-sky-500 text-white [&_svg]:size-2">
                                <IconDatabase />
                            </span>
                        ) : null}
                    </span>
                ),
                afterName: (s) => <StatusGlyph status={s.status} />,
            }}
        />
    ),
}

/** C: only the unusual kind is marked, at the end of the row, with a hover tooltip. */
export const C_TrailingGlyph: Story = {
    render: () => (
        <Frame
            title="C. Trailing glyph on materialized only"
            notes="Plain views carry no marker, since they are the default. Materialized views get a small refresh glyph after the name, and the tooltip carries the full kind, schedule and last run. The glyph is 14px, so it costs the name almost nothing."
            opts={{
                icon: () => <IconDocument />,
                tooltip: (s) => (
                    <div className="flex flex-col gap-0.5">
                        <span className="font-mono">{s.name}</span>
                        <span className="opacity-75">
                            {KIND_LABEL[s.kind]}
                            {s.kind === 'matview' ? ' · synced 2h ago' : ''}
                        </span>
                    </div>
                ),
                afterName: (s) =>
                    s.kind === 'matview' ? (
                        <>
                            <StatusGlyph status={s.status} />
                            {s.status ? null : <IconRefresh className="shrink-0 size-3.5 text-sky-500" />}
                        </>
                    ) : null,
            }}
        />
    ),
}

const GROUPED: { label: string; kind: Kind }[] = [
    { label: 'Views', kind: 'view' },
    { label: 'Materialized views', kind: 'matview' },
]

/** D: no per-row marker. Structure does it: two sub-groups. */
export const D_SeparateGroups: Story = {
    render: () => (
        <div className="flex flex-col gap-3 p-4 max-w-[760px]">
            <div>
                <h3 className="mb-1">D. Two sub-groups, no per-row marker</h3>
                <p className="text-secondary text-sm m-0">
                    Views and materialized views are listed under their own headings, with a count. Rows carry no marker
                    at all, so the name has the whole row. The cost: more vertical space, and a view you just
                    materialized jumps groups. Search results would need the marker, or a heading per group.
                </p>
            </div>
            <div className="flex gap-6 items-start">
                {[300, 220].map((width) => (
                    <div key={width} className="flex flex-col gap-1">
                        <span className="text-xs text-tertiary">
                            {width === 300 ? 'Default width (300px)' : 'Narrow (220px)'}
                        </span>
                        <div className="flex flex-col gap-2">
                            {GROUPED.map((g) => {
                                const samples = SAMPLES.filter((s) => s.kind === g.kind)
                                return (
                                    <div key={g.kind} className="flex flex-col gap-1">
                                        <div
                                            className="flex items-center gap-1 px-1 text-xs font-semibold text-secondary"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ width }}
                                        >
                                            {g.label}
                                            <span className="font-normal text-tertiary">{samples.length}</span>
                                        </div>
                                        <Tree
                                            width={width}
                                            samples={samples}
                                            opts={{
                                                icon: () =>
                                                    g.kind === 'matview' ? <IconDatabase /> : <IconDocument />,
                                                afterName: (s) => <StatusGlyph status={s.status} />,
                                            }}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    ),
}

/** E: independent of how the kind is shown. What happens to a name that does not fit. */
function MiddleName({ name }: { name: string }): JSX.Element {
    // Keep the last 10 characters visible. Names of one family share a prefix, so the end is the useful part.
    const tailLength = 10
    const split = name.length > tailLength * 2 ? name.length - tailLength : name.length
    return (
        <span className="flex min-w-0">
            <span className="truncate">{name.slice(0, split)}</span>
            <span className="shrink-0 whitespace-pre">{name.slice(split)}</span>
        </span>
    )
}

export const E_LongNames: Story = {
    render: () => {
        const base: Omit<RowOptions, 'renderName'> = {
            icon: (s) => (
                <span className="relative flex size-5 shrink-0 items-center justify-center">
                    <IconDocument className={s.kind === 'matview' ? 'text-sky-500' : 'text-tertiary'} />
                    {s.kind === 'matview' ? (
                        <span className="absolute -bottom-0.5 right-0 flex size-3 items-center justify-center rounded-full bg-sky-500 text-white [&_svg]:size-2">
                            <IconDatabase />
                        </span>
                    ) : null}
                </span>
            ),
            afterName: (s) => <StatusGlyph status={s.status} />,
        }
        const long = SAMPLES.filter((s) => s.name.startsWith('shop_'))
        return (
            <div className="flex flex-col gap-6 p-4">
                <div>
                    <h3 className="mb-1">E. Long names, two strategies</h3>
                    <p className="text-secondary text-sm m-0 max-w-[700px]">
                        With the text label gone the name already has the row. Wrapping to a second line is not offered,
                        because tree rows are a fixed height. These are what happens to a name that still does not fit.
                        Both use the option B icon, so the kind is not a variable here. Note how{' '}
                        <code>shop_dash_region_monthly_orders</code> and <code>shop_dash_region_monthly_refunds</code>{' '}
                        collapse into the same stub with end-ellipsis.
                    </p>
                </div>
                <div className="flex gap-6 items-start">
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-tertiary">1. End ellipsis (the baseline fix)</span>
                        <Tree samples={long} width={220} opts={base} />
                    </div>
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-tertiary">2. Middle ellipsis, keeps the end</span>
                        <Tree
                            samples={long}
                            width={220}
                            opts={{ ...base, renderName: (s) => <MiddleName name={s.name} /> }}
                        />
                    </div>
                </div>
            </div>
        )
    },
}

/** F: a combination to react to, so you are not only judging options in isolation. */
export const F_Combined: Story = {
    render: () => (
        <Frame
            title="F. Combined: B icon + C tooltip + middle ellipsis"
            notes="Corner-badge icon carries the kind, the name never loses space to a label and keeps its tail when it has to be cut, and the tooltip names the kind, so nothing relies on color alone."
            opts={{
                icon: (s) => (
                    <span className="relative flex size-5 shrink-0 items-center justify-center">
                        <IconDocument className={s.kind === 'matview' ? 'text-sky-500' : 'text-tertiary'} />
                        {s.kind === 'matview' ? (
                            <span className="absolute -bottom-0.5 right-0 flex size-3 items-center justify-center rounded-full bg-sky-500 text-white [&_svg]:size-2">
                                <IconDatabase />
                            </span>
                        ) : null}
                    </span>
                ),
                renderName: (s) => <MiddleName name={s.name} />,
                afterName: (s) => <StatusGlyph status={s.status} />,
                tooltip: (s) => (
                    <div className="flex flex-col gap-0.5">
                        <span className="font-mono">{s.name}</span>
                        <span className="flex items-center gap-1 opacity-75">
                            {KIND_LABEL[s.kind]}
                            {s.kind === 'matview' ? (
                                <>
                                    <IconClock className="size-3" /> synced 2h ago
                                </>
                            ) : null}
                        </span>
                    </div>
                ),
            }}
        />
    ),
}

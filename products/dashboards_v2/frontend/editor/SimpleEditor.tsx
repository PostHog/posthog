import { useValues } from 'kea'
import { useState, type ComponentType, type ReactNode } from 'react'

import {
    IconBolt,
    IconCode,
    IconDocument,
    IconEllipsis,
    IconFunnels,
    IconGraph,
    IconPieChart,
    IconRetention,
    IconStack,
    IconTrends,
} from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
    Textarea,
    cn,
} from '@posthog/quill'

import { Icon123, IconTableChart } from 'lib/lemon-ui/icons'
import { projectLogic } from 'scenes/projectLogic'

import { vizRegistry } from '../charts/registry'
import {
    EVENT_OPTIONS,
    applyBuilder,
    insightSource,
    liftBuilder,
    newInsight,
    newPanel,
    newPanelFor,
    setTargetBuilder,
    switchKind,
    withSource,
    withViz,
    type Builder,
    type EventsState,
} from '../explore/build'
import { ProjectScope, useOptions } from '../explore/Builders'
import { EventsBuilder } from '../explore/EventsBuilder'
import { useLocalCopy } from '../lib/useLocalCopy'
import { DashboardV2SamplePanel } from '../panel/DashboardV2SamplePanel'
import type { Panel } from '../spec'

const CENTRED = 'top-1/2 -translate-x-1/2 -translate-y-1/2 [--quill-dialog-top-gap:1rem]'

type IconType = ComponentType<{ className?: string }>

export function simpleQuery(panel: Panel): { refId: string; state: EventsState } | undefined {
    const targets = liftBuilder(panel).targets ?? []
    const first = targets[0]
    const builder = first?.builder as Builder | undefined
    if (!first || builder?.source !== 'events' || !targets.every((t) => t === first || t.builtBy === first.refId)) {
        return undefined
    }
    return { refId: first.refId, state: builder }
}

const LANGUAGE_NAMES: Record<string, string> = { hogql: 'SQL', sql: 'metrics SQL', promql: 'PromQL', logql: 'LogQL' }

function writtenIn(panel: Panel): string {
    const languages = new Set((panel.targets ?? []).map((t) => t.language))
    const names = [...languages].flatMap((language) => LANGUAGE_NAMES[language] ?? [])
    return names.length ? names.join(' and ') : 'a query the simple editor does not cover'
}

interface Shape {
    type: string
    label: string
    icon: IconType
}
const SHAPES: Shape[] = [
    { type: 'timeseries', label: 'Trend', icon: IconTrends },
    { type: 'bar', label: 'Bars', icon: IconGraph },
    { type: 'stat', label: 'Number', icon: Icon123 },
    { type: 'table', label: 'Table', icon: IconTableChart },
    { type: 'pie', label: 'Pie', icon: IconPieChart },
    { type: 'retention', label: 'Retention', icon: IconRetention },
]
const ALL_SHAPES: Shape[] = Object.entries(vizRegistry)
    .filter(([, def]) => def.needsData)
    .map(([type, def]) => SHAPES.find((s) => s.type === type) ?? { type, label: def.label, icon: IconStack })

export function SimpleTileEditor({
    id,
    panel,
    onChange,
    onClose,
    onAdvanced,
}: {
    id: string
    panel: Panel
    onChange: (next: Panel) => void
    onClose: () => void
    onAdvanced: () => void
}): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const projectId = String(currentProjectId)
    const [local, setLocal, flush] = useLocalCopy(panel, onChange)
    const [more, setMore] = useState(false)
    const q = simpleQuery(local)
    const text = local.viz?.type === 'text'
    const close = (): void => {
        flush()
        onClose()
    }
    const advanced = (): void => {
        flush()
        onAdvanced()
    }
    const shapes = more ? ALL_SHAPES : SHAPES
    return (
        <Dialog open onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className={CENTRED} data-attr="dashboard-v2-simple-editor">
                <DialogHeader>
                    <DialogTitle>{local.title || 'New panel'}</DialogTitle>
                </DialogHeader>
                <DialogBody
                    render={<div />}
                    className="grid grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] p-0 max-md:grid-cols-1"
                >
                    <div className="flex flex-col gap-3 border-r border-border bg-muted/30 p-4 max-md:border-r-0 max-md:border-b">
                        <div className="h-80">
                            <DashboardV2SamplePanel id={id} panel={local} />
                        </div>
                        <p className="text-xs text-muted-foreground">The preview updates as you edit.</p>
                    </div>
                    <div className="flex max-h-[70dvh] flex-col gap-6 overflow-y-auto p-4">
                        {text ? (
                            <Step n={1} title="Write it">
                                <Textarea
                                    rows={10}
                                    value={String(
                                        (local.viz.options as { markdown?: string } | undefined)?.markdown ?? ''
                                    )}
                                    onChange={(e) =>
                                        setLocal((p) => ({
                                            ...p,
                                            viz: { ...p.viz, options: { ...p.viz.options, markdown: e.target.value } },
                                        }))
                                    }
                                    placeholder="Markdown: ## a heading, **bold**, [a link](https://example.com)"
                                    data-attr="dashboard-v2-simple-markdown"
                                />
                            </Step>
                        ) : q ? (
                            <>
                                <Step n={1} title="Measure">
                                    <ProjectScope value={projectId}>
                                        <EventsBuilder
                                            projectId={projectId}
                                            state={q.state}
                                            onChange={(s) =>
                                                setLocal((p) =>
                                                    setTargetBuilder(p, q.refId, { ...s, source: 'events' })
                                                )
                                            }
                                        />
                                    </ProjectScope>
                                </Step>
                                <Step n={2} title="Show as">
                                    <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="Show as">
                                        {shapes.map((s) => {
                                            const on = local.viz?.type === s.type
                                            return (
                                                <button
                                                    key={s.type}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={on}
                                                    data-attr={`dashboard-v2-shape-${s.type}`}
                                                    onClick={() => setLocal((p) => withViz(p, { type: s.type }))}
                                                    className={cn(
                                                        'flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border px-1 py-2.5 text-xs transition-colors',
                                                        on
                                                            ? 'border-foreground bg-fill-selected font-medium text-foreground'
                                                            : 'border-border bg-card hover:bg-fill-hover'
                                                    )}
                                                >
                                                    <s.icon className="size-5" />
                                                    {s.label}
                                                </button>
                                            )
                                        })}
                                        {!more && (
                                            <button
                                                type="button"
                                                onClick={() => setMore(true)}
                                                className="flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed border-border px-1 py-2.5 text-xs text-muted-foreground hover:text-foreground"
                                                data-attr="dashboard-v2-shape-more"
                                            >
                                                <IconEllipsis className="size-5" />
                                                {ALL_SHAPES.length - SHAPES.length} more
                                            </button>
                                        )}
                                    </div>
                                </Step>
                            </>
                        ) : (
                            <Step n={1} title="Measure">
                                <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-4 text-sm">
                                    <span>
                                        This panel uses <b>{writtenIn(local)}</b>. Open it in the advanced editor to
                                        change what it measures.
                                    </span>
                                    <Button variant="outline" size="sm" className="self-start" onClick={advanced}>
                                        <IconCode /> Edit in the advanced editor
                                    </Button>
                                </div>
                            </Step>
                        )}
                        <Step n={text ? 2 : q ? 3 : 2} title="Details">
                            <Field>
                                <FieldLabel htmlFor="dashboard-v2-simple-title">Title</FieldLabel>
                                <Input
                                    id="dashboard-v2-simple-title"
                                    value={local.title ?? ''}
                                    onChange={(e) => setLocal((p) => ({ ...p, title: e.target.value }))}
                                    placeholder="What it shows, for example Sign-ups per day"
                                    data-attr="dashboard-v2-simple-title"
                                />
                            </Field>
                            <Field>
                                <FieldLabel htmlFor="dashboard-v2-simple-description">Description</FieldLabel>
                                <Input
                                    id="dashboard-v2-simple-description"
                                    value={local.description ?? ''}
                                    onChange={(e) =>
                                        setLocal((p) => ({ ...p, description: e.target.value || undefined }))
                                    }
                                    placeholder="One line under the title (optional)"
                                    data-attr="dashboard-v2-simple-description"
                                />
                            </Field>
                        </Step>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="link-muted"
                        className="sm:mr-auto"
                        onClick={advanced}
                        data-attr="dashboard-v2-open-advanced"
                    >
                        <IconCode /> Advanced editor
                    </Button>
                    <Button variant="primary" onClick={close} data-attr="dashboard-v2-simple-done">
                        Done
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <h3 className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                <span className="grid size-5 place-items-center rounded-full bg-foreground text-[10.5px] font-bold text-background">
                    {n}
                </span>
                {title}
            </h3>
            {children}
        </section>
    )
}

function breakdown(property: string, viz: Panel['viz'], title: string): Panel {
    const p = newPanel()
    const t = liftBuilder(p).targets![0]!
    const b = t.builder as EventsState
    const src = insightSource(b)
    const split = setTargetBuilder(p, t.refId, {
        ...withSource(b, { ...src, breakdownFilter: { breakdown: property, breakdown_type: 'event' } }),
        source: 'events',
    })
    return { ...withViz(split, viz), title }
}
const funnelPanel = (): Panel =>
    applyBuilder(
        { title: '', viz: { type: 'bar', options: { funnel: true } }, targets: [] },
        {
            source: 'events',
            ...switchKind({ insight: { query: newInsight('TrendsQuery', ['$pageview', null]) } }, 'FunnelsQuery'),
        }
    )
const trendOf = (event: string, title: string): Panel => ({
    ...applyBuilder(
        { title, viz: { type: 'timeseries' }, targets: [] },
        { source: 'events', insight: { query: newInsight('TrendsQuery', [event]) } }
    ),
    title,
})

function IconRankedBars({ className }: { className?: string }): JSX.Element {
    return <IconGraph className={cn('rotate-90', className)} />
}

interface Kind {
    key: string
    label: string
    hint: string
    icon: IconType
    make: () => Panel
}
const KINDS: Kind[] = [
    { key: 'trend', label: 'Trend', hint: 'How something changes over time', icon: IconTrends, make: newPanel },
    {
        key: 'number',
        label: 'Key number',
        hint: 'One number and how it moved',
        icon: Icon123,
        make: () => withViz(newPanel(), { type: 'stat' }),
    },
    {
        key: 'funnel',
        label: 'Funnel',
        hint: 'Where people drop off between steps',
        icon: IconFunnels,
        make: funnelPanel,
    },
    {
        key: 'retention',
        label: 'Retention',
        hint: 'Who comes back, week by week',
        icon: IconRetention,
        make: () => newPanelFor('retention'),
    },
    {
        key: 'top',
        label: 'Top list',
        hint: 'Pages, sources or countries, ranked',
        icon: IconRankedBars,
        make: () => breakdown('$pathname', { type: 'bar', options: { horizontal: true } }, 'Top pages'),
    },
    {
        key: 'breakdown',
        label: 'Breakdown',
        hint: 'A total split into its parts',
        icon: IconPieChart,
        make: () => breakdown('$browser', { type: 'pie', options: { donut: true } }, 'Visitors by browser'),
    },
    {
        key: 'note',
        label: 'Note',
        hint: 'Text, headings and links',
        icon: IconDocument,
        make: () => ({ title: '', viz: { type: 'text', options: { markdown: '' } } }),
    },
]

export function AddTileGallery({
    onAdd,
    onAdvanced,
    onClose,
}: {
    onAdd: (panel: Panel) => void
    onAdvanced: () => void
    onClose: () => void
}): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const events = useOptions(String(currentProjectId), 'hogql', EVENT_OPTIONS.events())
    const names: string[] = events.data ?? []
    const top = names.filter((e) => !e.startsWith('$') || e === '$pageview').slice(0, 3)
    return (
        <Dialog open onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent
                className={cn(CENTRED, 'max-w-[min(56rem,calc(100vw-3rem))]')}
                data-attr="dashboard-v2-add-panel-gallery"
            >
                <DialogHeader>
                    <DialogTitle>Add a panel</DialogTitle>
                    <DialogDescription>Pick what you want to see. You can change it afterwards.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-5">
                        <div className="grid grid-cols-4 gap-2.5 max-sm:grid-cols-2">
                            {KINDS.map((k) => (
                                <button
                                    key={k.key}
                                    type="button"
                                    data-attr={`dashboard-v2-add-${k.key}`}
                                    onClick={() => onAdd(k.make())}
                                    className="flex cursor-pointer flex-col gap-1.5 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-foreground"
                                >
                                    <span className="grid h-14 place-items-center rounded-md bg-muted">
                                        <k.icon className="size-6 text-muted-foreground" />
                                    </span>
                                    <span className="text-sm font-semibold">{k.label}</span>
                                    <span className="text-xs leading-snug text-muted-foreground">{k.hint}</span>
                                </button>
                            ))}
                        </div>
                        {top.length > 0 && (
                            <div className="flex flex-col gap-2">
                                <span className="text-xs font-semibold text-muted-foreground">
                                    From your busiest events
                                </span>
                                <div className="grid grid-cols-3 gap-2.5 max-sm:grid-cols-1">
                                    {top.map((e) => {
                                        const name = e === '$pageview' ? 'Page views' : e
                                        return (
                                            <button
                                                key={e}
                                                type="button"
                                                data-attr="dashboard-v2-add-event"
                                                onClick={() => onAdd(trendOf(e, `${name} per day`))}
                                                className="flex cursor-pointer flex-col gap-1 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-foreground"
                                            >
                                                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                                    <IconBolt className="size-3" />
                                                    {e}
                                                    {events.details?.[e] &&
                                                        ` · ${Number(events.details[e]).toLocaleString()} this week`}
                                                </span>
                                                <span className="text-sm font-semibold">{name} per day</span>
                                            </button>
                                        )
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter className="sm:justify-start">
                    <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                        <span>Prefer to write the query yourself?</span>
                        <Button
                            variant="link-muted"
                            size="sm"
                            onClick={onAdvanced}
                            data-attr="dashboard-v2-add-advanced"
                        >
                            <IconCode /> SQL, PromQL or LogQL
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

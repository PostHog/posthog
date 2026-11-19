import { useValues } from 'kea'
import { useEffect, useRef, useState, type MutableRefObject } from 'react'

import {
    IconActivity,
    IconCopy,
    IconDecisionTree,
    IconExpand45,
    IconEye,
    IconHide,
    IconList,
    IconPencil,
    IconPlus,
    IconSidePanel,
    IconTrash,
    IconX,
} from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogContent,
    DialogTitle,
    Input,
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
    Switch,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Textarea,
} from '@posthog/quill'

import { projectLogic } from 'scenes/projectLogic'

import { CHART_UNITS, THRESHOLD_COLORS, chartType } from '../charts/chartTypes'
import { dashboardV2Logic } from '../dashboard/dashboardV2Logic'
import {
    defaultQuery,
    freeRefs,
    liftBuilder,
    panelSource,
    parseQuery,
    setTargetBuilder,
    toManual,
    withPanelSource,
    withViz,
    type Builder,
    type PanelSource,
} from '../explore/build'
import { BuilderTime, QueryBuilder } from '../explore/Builders'
import { useUsage } from '../lib/api'
import { useLocalCopy } from '../lib/useLocalCopy'
import { DashboardV2SamplePanel } from '../panel/DashboardV2SamplePanel'
import type { Panel as PanelSpec, Target, Threshold } from '../spec'
import { confirmDialog } from './Confirm'
import { FieldRow, OptionSelect, Section, Segmented } from './OptionsForm'
import type { PanelEditorLayout, PanelEditorMode } from './panelEditorLogic'
import { VizOptions } from './VizPicker'

const DESCRIPTION_MODES = [
    ['info', 'Beside the title'],
    ['below', 'Below the title'],
    ['hidden', 'Hidden'],
] as const

export type PanelPopupProps = {
    id: string
    panel: PanelSpec
    mode: PanelEditorMode
    layout: PanelEditorLayout
    onMode: (mode: PanelEditorMode) => void
    onLayout: (layout: PanelEditorLayout) => void
    onClose: () => void
    canEdit?: boolean
    onChange?: (panel: PanelSpec) => void
    onDuplicate?: (id: string) => void
    onRemove?: (id: string) => void
}
type Tab = 'query' | 'viz' | 'field' | 'json'

const WIDTH_KEY = 'dashboards-v2.panel-editor-width'
const FIT_KEY = 'dashboards-v2.panel-view-fit'

function dashboardRatio(id: string): number | undefined {
    const el = [...document.querySelectorAll(`[data-panel="${CSS.escape(id)}"]`)].find(
        (e) => !e.closest('[data-panel-editor]')
    )
    const r = el?.getBoundingClientRect()
    return r && r.width > 0 && r.height > 0 ? r.width / r.height : undefined
}

export function PanelPopup({
    id,
    panel,
    mode,
    layout,
    onMode,
    onLayout,
    onClose,
    canEdit,
    onChange,
    onDuplicate,
    onRemove,
}: PanelPopupProps): JSX.Element {
    const [ratio, setRatio] = useState(() => dashboardRatio(id))
    useEffect(() => {
        if (ratio) {
            return
        }
        const timers = [100, 400, 1200].map((ms) => setTimeout(() => setRatio((r) => r ?? dashboardRatio(id)), ms))
        return () => timers.forEach(clearTimeout)
    }, [id, ratio])
    const [fit, setFit] = useState(() => localStorage.getItem(FIT_KEY) ?? 'ratio')
    const flushRef = useRef<() => void>()
    const leave = (then: () => void): void => {
        flushRef.current?.()
        then()
    }
    const close = (): void => leave(onClose)
    const modal = layout === 'modal'
    const editing = mode === 'edit' && !!canEdit && !!onChange
    const title = (
        <div className="flex min-w-0 items-center gap-2">
            <div className="truncate text-sm font-semibold">{panel.title || 'Untitled panel'}</div>
            <code className="truncate text-xs text-muted-foreground">{id}</code>
        </div>
    )
    const controls = (
        <>
            <Tabs
                value={editing ? 'edit' : 'view'}
                onValueChange={(value: string) => leave(() => onMode(value as PanelEditorMode))}
            >
                <TabsList className="h-7" data-attr="dashboard-v2-panel-mode">
                    <TabsTrigger value="view" className="px-2 text-xs">
                        <IconEye className="size-3.5" /> View
                    </TabsTrigger>
                    {canEdit && (
                        <TabsTrigger value="edit" className="px-2 text-xs">
                            <IconPencil className="size-3.5" /> Edit
                        </TabsTrigger>
                    )}
                </TabsList>
            </Tabs>
            {!editing && ratio && (
                <Segmented
                    className="w-auto"
                    options={[
                        ['ratio', 'Dashboard shape'],
                        ['fill', 'Fill'],
                    ]}
                    value={fit}
                    onChange={(value) => {
                        setFit(value)
                        localStorage.setItem(FIT_KEY, value)
                    }}
                />
            )}
            <div className="flex-1" />
            {onDuplicate && (
                <Button
                    variant="outline"
                    size="xs"
                    className="h-7"
                    onClick={() => leave(() => onDuplicate(id))}
                    data-attr="dashboard-v2-panel-duplicate"
                >
                    <IconCopy /> Duplicate
                </Button>
            )}
            {onRemove && (
                <Button
                    variant="outline"
                    size="xs"
                    className="h-7"
                    onClick={() => onRemove(id)}
                    data-attr="dashboard-v2-panel-remove"
                >
                    <IconTrash /> Remove
                </Button>
            )}
        </>
    )
    const actions = (
        <div className="flex shrink-0 items-center gap-1">
            <Button
                variant="default"
                size="icon-sm"
                tooltip={modal ? 'Dock to the side of the dashboard' : 'Open large'}
                aria-label={modal ? 'Dock to the side of the dashboard' : 'Open large'}
                data-attr="dashboard-v2-panel-layout"
                onClick={() => leave(() => onLayout(modal ? 'side' : 'modal'))}
            >
                {modal ? <IconSidePanel /> : <IconExpand45 />}
            </Button>
            <Button
                variant="default"
                size="icon-sm"
                tooltip="Close"
                aria-label="Close"
                onClick={close}
                data-attr="dashboard-v2-panel-close"
            >
                <IconX />
            </Button>
        </div>
    )
    const header = (
        <div className="flex shrink-0 flex-col gap-2 border-b px-3 py-2">
            <div className="flex items-center gap-2">
                {title}
                <div className="ml-auto">{actions}</div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">{controls}</div>
        </div>
    )
    const body = editing ? (
        <EditBody key={id} id={id} panel={panel} modal={modal} onChange={onChange} flushRef={flushRef} />
    ) : fit === 'ratio' && ratio ? (
        <div className="flex h-full items-center justify-center bg-muted/30 p-3 [container-type:size]">
            <div style={{ aspectRatio: ratio, width: `min(100cqw, calc(100cqh * ${ratio}))` }}>
                <DashboardV2SamplePanel id={id} panel={panel} />
            </div>
        </div>
    ) : (
        <div className="h-full bg-muted/30 p-3">
            <DashboardV2SamplePanel id={id} panel={panel} />
        </div>
    )

    if (modal) {
        return (
            <Dialog open onOpenChange={(open: boolean) => !open && close()}>
                <DialogContent
                    size="full"
                    showCloseButton={false}
                    className="flex h-[calc(100dvh-6rem)] max-h-none max-w-[calc(100vw-6rem)] flex-col gap-0 overflow-hidden p-0"
                    style={{ '--quill-dialog-top-gap': '3rem' } as React.CSSProperties}
                    data-panel-editor
                    data-attr="dashboard-v2-panel-editor"
                >
                    <DialogTitle className="sr-only">{panel.title || id}</DialogTitle>
                    {header}
                    <div className="min-h-0 flex-1">{body}</div>
                </DialogContent>
            </Dialog>
        )
    }

    return (
        <SideSheet title={panel.title || id} header={header} onClose={close}>
            {body}
        </SideSheet>
    )
}

function SideSheet({
    title,
    header,
    children,
    onClose,
}: {
    title: string
    header: React.ReactNode
    children: React.ReactNode
    onClose: () => void
}): JSX.Element {
    const vw = window.innerWidth
    const width = Math.min(Number(localStorage.getItem(WIDTH_KEY)) || 560, vw)
    return (
        <Dialog open modal={false} disablePointerDismissal onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent
                showCloseButton={false}
                overlayClassName="hidden"
                className="pointer-events-none inset-0 block h-dvh max-h-none w-screen max-w-none translate-x-0 scale-100 rounded-none bg-transparent p-0 shadow-none transition-none"
                data-panel-editor
                data-attr="dashboard-v2-panel-editor"
            >
                <DialogTitle className="sr-only">{title}</DialogTitle>
                <ResizablePanelGroup orientation="horizontal" className="h-full">
                    <ResizablePanel />
                    <ResizableHandle withHandle className="pointer-events-auto" />
                    <ResizablePanel
                        defaultSize={width}
                        minSize={Math.min(380, vw)}
                        maxSize="94"
                        className="pointer-events-auto"
                        onResize={(size: { inPixels: number }) =>
                            localStorage.setItem(WIDTH_KEY, String(Math.round(size.inPixels)))
                        }
                    >
                        <aside className="flex h-full flex-col border-l bg-background shadow-lg">
                            {header}
                            <div className="min-h-0 flex-1">{children}</div>
                        </aside>
                    </ResizablePanel>
                </ResizablePanelGroup>
            </DialogContent>
        </Dialog>
    )
}

function EditBody({
    id,
    panel,
    modal,
    onChange,
    flushRef,
}: {
    id: string
    panel: PanelSpec
    modal: boolean
    onChange: (panel: PanelSpec) => void
    flushRef: MutableRefObject<(() => void) | undefined>
}): JSX.Element {
    const { timeRange } = useValues(dashboardV2Logic)
    const { currentProjectId } = useValues(projectLogic)
    const [local, setLocal, flush] = useLocalCopy(panel, onChange)
    useEffect(() => {
        flushRef.current = flush
        return () => {
            flushRef.current = undefined
        }
    }, [flush, flushRef])
    const preview = <DashboardV2SamplePanel id={id} panel={local} onEditPanel={setLocal} />
    const form = (tabs?: Tab[]): JSX.Element => (
        <PanelForm
            panel={local}
            projectId={String(currentProjectId ?? '')}
            tabs={tabs}
            time={timeRange}
            onChange={setLocal}
        />
    )
    if (modal) {
        return (
            <ResizablePanelGroup orientation="horizontal" className="h-full">
                <ResizablePanel defaultSize="62" minSize={360}>
                    <ResizablePanelGroup orientation="vertical" className="h-full">
                        <ResizablePanel defaultSize="48" minSize={140}>
                            <div className="h-full bg-muted/30 p-3">{preview}</div>
                        </ResizablePanel>
                        <ResizableHandle withHandle />
                        <ResizablePanel minSize={140}>
                            <div className="h-full overflow-auto p-3 pb-24">{form(['query', 'json'])}</div>
                        </ResizablePanel>
                    </ResizablePanelGroup>
                </ResizablePanel>
                <ResizableHandle withHandle />
                <ResizablePanel minSize={320}>
                    <div className="h-full overflow-auto p-3 pb-24">{form(['viz', 'field'])}</div>
                </ResizablePanel>
            </ResizablePanelGroup>
        )
    }
    return (
        <ResizablePanelGroup orientation="vertical" className="h-full">
            <ResizablePanel defaultSize={240} minSize={120}>
                <div className="h-full bg-muted/30 p-2">{preview}</div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel minSize={160}>
                <div className="h-full overflow-auto p-3 pb-24">{form()}</div>
            </ResizablePanel>
        </ResizablePanelGroup>
    )
}

export function toBuilders(p: PanelSpec): PanelSpec {
    return {
        ...p,
        targets: p.targets?.map((t) => {
            const read = t.language === 'promql' && !t.builder ? parseQuery(t) : undefined
            return read?.complete ? { ...t, builder: read.builder } : t
        }),
    }
}

export const LANGUAGES = [
    ['promql', 'PromQL'],
    ['logql', 'LogQL'],
    ['hogql', 'HogQL'],
    ['sql', 'Metrics SQL'],
    ['insight', 'Insight'],
] as const
const PLACEHOLDER: Record<string, string> = {
    promql: 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="$namespace"}[$window]))',
    logql: 'sum by (level) (count_over_time({k8s.namespace.name="$namespace"} |= "error" [5m]))',
    hogql: 'SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE timestamp >= {date_from} GROUP BY t ORDER BY t',
}

const TABS: [Tab, string][] = [
    ['query', 'Queries'],
    ['viz', 'Display'],
    ['field', 'Field'],
    ['json', 'JSON'],
]
const SOURCES: [PanelSource, React.ReactNode][] = [
    [
        'series',
        <>
            <IconActivity className="size-3.5" /> Events & metrics
        </>,
    ],
    [
        'logs',
        <>
            <IconList className="size-3.5" /> Logs
        </>,
    ],
    [
        'traces',
        <>
            <IconDecisionTree className="size-3.5" /> Traces
        </>,
    ],
]

const NO_UNIT = 'none'
const UNITS = CHART_UNITS.map(([unit, label]) => [unit || NO_UNIT, label] as const)

const DEFAULT_TIME = { from: 'now-1h', to: 'now' }
export function PanelForm({
    panel,
    projectId,
    tabs = TABS.map(([t]) => t),
    time = DEFAULT_TIME,
    onChange,
}: {
    panel: PanelSpec
    projectId: string
    tabs?: Tab[]
    time?: { from: string; to: string }
    onChange: (p: PanelSpec) => void
}): JSX.Element {
    const local = liftBuilder(panel)
    const [json, setJson] = useState<string>()
    const [jsonError, setJsonError] = useState<string>()
    const set = (patch: Partial<PanelSpec>): void => onChange({ ...local, ...patch })
    const targets = local.targets ?? []
    const addQuery = (): void => {
        const last = targets.filter((t) => !t.builtBy).at(-1)
        const [ref] = freeRefs(
            targets.map((t) => t.refId),
            1
        )
        if (!last || last.builder) {
            onChange(
                setTargetBuilder(local, ref!, { source: (last?.builder as Builder | undefined)?.source ?? 'events' })
            )
        } else {
            set({ targets: [...targets, { refId: ref!, language: last.language, query: '' }] })
        }
    }
    const fc = local.fieldConfig ?? {}
    const source = panelSource(local)
    const sources = SOURCES.filter(([value]) => value === 'series' || value === source || !!chartType(value))
    const stash = useRef<Partial<Record<PanelSource, PanelSpec>>>({})
    const pickSource = (v: string): void => {
        if (v === source) {
            return
        }
        stash.current[source] = local
        const back = stash.current[v as PanelSource]
        onChange(
            back
                ? { ...local, title: back.title, targets: back.targets, viz: back.viz, fieldConfig: back.fieldConfig }
                : withPanelSource(local, v as PanelSource)
        )
    }
    return (
        <BuilderTime value={time}>
            <Tabs defaultValue={tabs[0]}>
                <TabsList
                    variant="line"
                    className="sticky top-[var(--sticky-top,-0.75rem)] z-20 -mx-3 -mt-3 h-auto w-[calc(100%+1.5rem)] justify-start border-b bg-background px-2 pt-1"
                >
                    {TABS.filter(([t]) => tabs.includes(t)).map(([t, l]) => (
                        <TabsTrigger key={t} value={t} className="flex-none px-2">
                            {l}
                        </TabsTrigger>
                    ))}
                </TabsList>
                <TabsContent value="query" className="flex flex-col gap-3 pt-3">
                    {sources.length > 1 && <Segmented options={sources} value={source} onChange={pickSource} />}
                    <FieldRow label="Title" asLabel>
                        <Input
                            value={local.title ?? ''}
                            onChange={(e) => set({ title: e.target.value })}
                            data-attr="dashboard-v2-panel-title"
                        />
                    </FieldRow>
                    <FieldRow label="Description">
                        <div className="flex gap-2">
                            <Input
                                className="flex-1"
                                aria-label="Description"
                                value={local.description ?? ''}
                                onChange={(e) => set({ description: e.target.value })}
                            />
                            <OptionSelect
                                className="w-36 text-xs"
                                aria-label="Show description"
                                options={DESCRIPTION_MODES}
                                value={local.descriptionMode ?? 'info'}
                                onChange={(v) => set({ descriptionMode: v === 'info' ? undefined : v })}
                            />
                        </div>
                    </FieldRow>
                    {source !== 'series' ? (
                        <BuiltQuery panel={local} target={targets[0]!} projectId={projectId} onChange={onChange} />
                    ) : (
                        <>
                            {targets
                                .filter((t) => !t.builtBy)
                                .map((t) => (
                                    <QueryCard
                                        key={t.refId}
                                        panel={local}
                                        target={t}
                                        projectId={projectId}
                                        onChange={onChange}
                                    />
                                ))}
                            <Button variant="outline" size="sm" onClick={addQuery} data-attr="dashboard-v2-add-query">
                                <IconPlus /> Add query
                            </Button>
                            <div className="text-[11px] text-muted-foreground">
                                Variables: <code>$name</code>, <code>${'{name:regex}'}</code>, <code>$__interval</code>,{' '}
                                <code>$__range</code>. HogQL also takes <code>{'{date_from}'}</code> and{' '}
                                <code>{'{date_to}'}</code>.
                            </div>
                            <Section
                                title="Query options"
                                defaultOpen={
                                    !!(
                                        local.timeFrom ||
                                        local.timeShift ||
                                        local.interval ||
                                        local.maxDataPoints ||
                                        local.compare
                                    )
                                }
                            >
                                <FieldRow
                                    label="Compare with"
                                    description="Runs each query again for the range before, or for a day or a week ago. Charts draw it dashed and a number shows the change"
                                >
                                    <Segmented
                                        options={[
                                            ['off', 'Off'],
                                            ['previous', 'Previous period'],
                                            ['1d', 'A day ago'],
                                            ['1w', 'A week ago'],
                                            ...(local.compare && !['previous', '1d', '1w'].includes(local.compare)
                                                ? [[local.compare, local.compare] as const]
                                                : []),
                                        ]}
                                        value={local.compare ?? 'off'}
                                        onChange={(v) => set({ compare: v === 'off' ? undefined : v })}
                                    />
                                </FieldRow>
                                <FieldRow
                                    label="Incomplete period"
                                    description="The last bucket while it is still filling in (today so far). Auto draws it dashed, unless a query is PromQL or LogQL. Estimate scales it to a whole bucket (counts and sums)"
                                >
                                    <Segmented
                                        options={[
                                            ['auto', 'Auto'],
                                            ['solid', 'Solid'],
                                            ['dashed', 'Dashed'],
                                            ['estimate', 'Estimate'],
                                            ['hidden', 'Hidden'],
                                        ]}
                                        value={local.incomplete ?? 'auto'}
                                        onChange={(v) =>
                                            set({
                                                incomplete:
                                                    v === 'auto'
                                                        ? undefined
                                                        : (v as NonNullable<PanelSpec['incomplete']>),
                                            })
                                        }
                                    />
                                </FieldRow>
                                <div className="grid grid-cols-2 gap-2">
                                    <FieldRow
                                        label="Relative time"
                                        description="This panel shows the last 6h, 24h or 7d instead of the dashboard's range"
                                    >
                                        <Input
                                            className="h-8 text-xs"
                                            placeholder="Dashboard range"
                                            value={local.timeFrom ?? ''}
                                            onChange={(e) => set({ timeFrom: e.target.value.trim() || undefined })}
                                            data-attr="dashboard-v2-panel-time-from"
                                        />
                                    </FieldRow>
                                    <FieldRow
                                        label="Time shift"
                                        description="Moves the range back by 1h, 1d or 7d to compare with the past"
                                    >
                                        <Input
                                            className="h-8 text-xs"
                                            placeholder="None"
                                            value={local.timeShift ?? ''}
                                            onChange={(e) => set({ timeShift: e.target.value.trim() || undefined })}
                                        />
                                    </FieldRow>
                                    <FieldRow
                                        label="Min interval"
                                        description="The step never goes below this, for example 1m"
                                    >
                                        <Input
                                            className="h-8 text-xs"
                                            placeholder="Auto"
                                            value={local.interval ?? ''}
                                            onChange={(e) => set({ interval: e.target.value.trim() || undefined })}
                                        />
                                    </FieldRow>
                                    <FieldRow
                                        label="Max data points"
                                        description="The most points per series, which sets the step"
                                    >
                                        <NumberInput
                                            value={local.maxDataPoints}
                                            placeholder="Auto"
                                            onChange={(maxDataPoints) => set({ maxDataPoints })}
                                        />
                                    </FieldRow>
                                </div>
                            </Section>
                        </>
                    )}
                </TabsContent>
                <TabsContent value="viz" className="pt-3">
                    <VizOptions panel={local} onChange={(viz) => onChange(withViz(local, viz))} />
                </TabsContent>
                <TabsContent value="field" className="flex flex-col gap-2 pt-3">
                    <Section title="Standard options">
                        <FieldRow label="Unit" description="How values are formatted">
                            <OptionSelect
                                className="h-8 w-full text-xs"
                                aria-label="Unit"
                                options={UNITS}
                                value={fc.unit || NO_UNIT}
                                onChange={(unit) =>
                                    set({ fieldConfig: { ...fc, unit: unit === NO_UNIT ? undefined : unit } })
                                }
                            />
                        </FieldRow>
                        <div className="grid grid-cols-2 gap-2">
                            <FieldRow label="Min">
                                <NumberInput
                                    value={fc.min}
                                    placeholder="Auto"
                                    onChange={(min) => set({ fieldConfig: { ...fc, min } })}
                                />
                            </FieldRow>
                            <FieldRow label="Max">
                                <NumberInput
                                    value={fc.max}
                                    placeholder="Auto"
                                    onChange={(max) => set({ fieldConfig: { ...fc, max } })}
                                />
                            </FieldRow>
                        </div>
                    </Section>
                    <Section title="Thresholds">
                        <ThresholdsEditor
                            value={fc.thresholds}
                            onChange={(thresholds) => set({ fieldConfig: { ...fc, thresholds } })}
                        />
                    </Section>
                </TabsContent>
                <TabsContent value="json" className="flex flex-col gap-2 pt-3">
                    <Textarea
                        rows={22}
                        className="font-mono text-xs"
                        aria-label="Panel JSON"
                        value={json ?? JSON.stringify(local, null, 2)}
                        onChange={(e) => setJson(e.target.value)}
                    />
                    {jsonError && <div className="text-xs text-destructive-foreground">{jsonError}</div>}
                    <Button
                        size="sm"
                        disabled={json === undefined}
                        data-attr="dashboard-v2-panel-json-apply"
                        onClick={() => {
                            try {
                                onChange(JSON.parse(json!))
                                setJson(undefined)
                                setJsonError(undefined)
                            } catch (e) {
                                setJsonError((e as Error).message)
                            }
                        }}
                    >
                        Apply JSON
                    </Button>
                </TabsContent>
            </Tabs>
        </BuilderTime>
    )
}

function BuiltQuery({
    panel,
    target,
    projectId,
    onChange,
}: {
    panel: PanelSpec
    target: Target
    projectId: string
    onChange: (p: PanelSpec) => void
}): JSX.Element {
    return (
        <>
            <QueryBuilder
                projectId={projectId}
                state={target.builder as Builder}
                empty={!target.query}
                onChange={(nb) => onChange(setTargetBuilder(panel, target.refId, nb))}
            />
            <Section
                title="SQL"
                defaultOpen={false}
                actions={
                    <Button
                        variant="outline"
                        size="xs"
                        className="mr-2"
                        tooltip="Write the queries by hand. The builder stops writing them."
                        onClick={() => onChange(toManual(panel, target.refId))}
                    >
                        Edit SQL
                    </Button>
                }
            >
                {(panel.targets ?? [])
                    .filter((x) => x.query)
                    .map((x) => (
                        <pre
                            key={x.refId}
                            className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border bg-muted/30 p-2 font-mono text-[11px] text-muted-foreground"
                        >
                            {x.query}
                        </pre>
                    ))}
            </Section>
        </>
    )
}

function QueryCard({
    panel,
    target: t,
    projectId,
    onChange,
}: {
    panel: PanelSpec
    target: Target
    projectId: string
    onChange: (p: PanelSpec) => void
}): JSX.Element {
    const [manual, setManual] = useState(false)
    const b = (t.builder ?? (!manual && t.language === 'insight' ? parseQuery(t)?.builder : undefined)) as
        | Builder
        | undefined
    const targets = panel.targets ?? []
    const written =
        b?.source === 'events' ? [] : [t, ...targets.filter((x) => x.builtBy === t.refId)].filter((x) => x.query)
    const lastBuilder = useRef<Builder | undefined>(b)
    const lastBy = useRef<Partial<Record<string, Builder>>>({})
    if (b) {
        lastBuilder.current = b
        lastBy.current[b.source] = b
    }
    const group = (x: Target): boolean => x.refId === t.refId || x.builtBy === t.refId
    const setT = (patch: Partial<Target>): void =>
        onChange({ ...panel, targets: targets.map((x) => (x.refId === t.refId ? { ...x, ...patch } : x)) })
    const toBuilder = async (source: Builder['source']): Promise<void> => {
        const read = parseQuery(t)
        const parsed = read?.builder.source === source ? read : undefined
        if (
            parsed &&
            !parsed.complete &&
            !(await confirmDialog({
                title: `Build query ${t.refId} from dropdowns?`,
                body: 'The builder keeps the metric or log stream, grouping and filters it can show. The rest of this query (functions, windows, other clauses) is replaced.',
                confirm: 'Use the builder',
                destructive: false,
            }))
        ) {
            return
        }
        if (
            !parsed &&
            t.query.trim() &&
            !(await confirmDialog({
                title: `Build query ${t.refId} from dropdowns?`,
                body: "The builder can't read this query, so it is replaced by what you pick.",
                confirm: 'Use the builder',
                destructive: false,
            }))
        ) {
            return
        }
        onChange(setTargetBuilder(panel, t.refId, parsed?.builder ?? lastBy.current[source] ?? { source }))
    }
    const usage = useUsage(projectId)
    const byLanguage = useRef<Record<string, string>>({})
    const setLanguage = (language: Target['language']): void => {
        if (language === t.language) {
            return
        }
        byLanguage.current[t.language] = t.query
        const top = Object.entries(usage.data?.metrics ?? {}).sort((x, y) => y[1] - x[1])[0]?.[0]
        setT({
            language,
            query:
                byLanguage.current[language] ??
                defaultQuery(language, {
                    builder: lastBuilder.current ?? parseQuery(t)?.builder,
                    metric: top,
                    logsViz: panel.viz?.type === 'logs',
                }),
        })
    }
    return (
        <div
            className="flex flex-col gap-2.5 rounded-lg border bg-card p-2.5 shadow-xs"
            data-attr={`dashboard-v2-query-${t.refId}`}
        >
            <div className="flex flex-wrap items-center gap-2">
                <code className="text-xs font-semibold">{t.refId}</code>
                <Segmented
                    options={[
                        ['events', 'Events'],
                        ['metrics', 'Metrics'],
                        ...(b?.source === 'logs' ? [['logs', 'Logs'] as const] : []),
                        ...(b?.source === 'traces' ? [['traces', 'Traces'] as const] : []),
                        ['query', 'Query'],
                    ]}
                    value={b ? b.source : 'query'}
                    onChange={(v) => {
                        setManual(v === 'query')
                        if (v === 'query') {
                            if (t.builder) {
                                onChange(toManual(panel, t.refId))
                            }
                        } else if (b) {
                            if (v !== b.source) {
                                onChange(
                                    setTargetBuilder(panel, t.refId, lastBy.current[v] ?? ({ source: v } as Builder))
                                )
                            }
                        } else {
                            void toBuilder(v as Builder['source'])
                        }
                    }}
                />
                {!b && (
                    <OptionSelect
                        className="h-7 w-28 text-xs"
                        aria-label="Query language"
                        options={LANGUAGES}
                        value={t.language}
                        onChange={setLanguage}
                    />
                )}
                {!b && (
                    <label className="flex items-center gap-1 text-xs">
                        <Switch checked={!!t.instant} onCheckedChange={(c: boolean) => setT({ instant: c })} /> Instant
                    </label>
                )}
                <Button
                    variant="default"
                    size="icon-xs"
                    className={`ml-auto ${t.hide ? 'text-muted-foreground' : ''}`}
                    tooltip={
                        t.hide
                            ? 'Hidden, so it is not run or drawn. Click to show it.'
                            : "Hide the query. It stays in the panel but doesn't run or draw."
                    }
                    aria-label={`${t.hide ? 'Show' : 'Hide'} query ${t.refId}`}
                    aria-pressed={!!t.hide}
                    data-attr="dashboard-v2-query-hide"
                    onClick={() =>
                        onChange({ ...panel, targets: targets.map((x) => (group(x) ? { ...x, hide: !t.hide } : x)) })
                    }
                >
                    {t.hide ? <IconHide /> : <IconEye />}
                </Button>
                <Button
                    variant="default"
                    size="icon-xs"
                    tooltip="Remove query"
                    aria-label={`Remove query ${t.refId}`}
                    data-attr="dashboard-v2-query-remove"
                    onClick={() => onChange({ ...panel, targets: targets.filter((x) => !group(x)) })}
                >
                    <IconTrash />
                </Button>
            </div>
            {b ? (
                <>
                    <QueryBuilder
                        projectId={projectId}
                        state={b}
                        empty={!t.query}
                        onChange={(nb) => onChange(setTargetBuilder(panel, t.refId, nb))}
                    />
                    {written.map((x) => (
                        <pre
                            key={x.refId}
                            className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-md border bg-muted/30 p-2 font-mono text-[11px] text-muted-foreground"
                            title="Written by the builder. Switch to Query to edit it."
                        >
                            <span className="font-semibold">
                                {x.refId} · {x.language}
                            </span>
                            {'\n'}
                            {x.query}
                        </pre>
                    ))}
                </>
            ) : (
                <>
                    <Textarea
                        rows={t.language === 'insight' ? 12 : 4}
                        className="font-mono text-xs"
                        aria-label={`Query ${t.refId}`}
                        value={t.query}
                        onChange={(e) => setT({ query: e.target.value })}
                        placeholder={PLACEHOLDER[t.language] ?? PLACEHOLDER.promql}
                    />
                    <Input
                        className="h-7 text-xs"
                        placeholder="Legend, for example {{pod}}"
                        aria-label="Legend"
                        value={t.legend ?? ''}
                        onChange={(e) => setT({ legend: e.target.value || undefined })}
                    />
                </>
            )}
        </div>
    )
}

function NumberInput({
    value,
    placeholder,
    onChange,
}: {
    value?: number
    placeholder?: string
    onChange: (v: number | undefined) => void
}): React.JSX.Element {
    const [text, setText] = useState(value === undefined ? '' : String(value))
    useEffect(() => {
        if (Number(text) !== value || text === '') {
            setText(value === undefined ? '' : String(value))
        }
    }, [value])
    return (
        <Input
            type="number"
            className="h-8 text-xs"
            placeholder={placeholder}
            value={text}
            onChange={(e) => {
                setText(e.target.value)
                const n = e.target.value === '' ? undefined : Number(e.target.value)
                if (n === undefined || !Number.isNaN(n)) {
                    onChange(n)
                }
            }}
        />
    )
}

function ThresholdsEditor({
    value = [],
    onChange,
}: {
    value?: Threshold[]
    onChange: (t: Threshold[] | undefined) => void
}): React.JSX.Element {
    const rows = value.map((t, i) => ({ ...t, i })).sort((a, b) => b.value - a.value)
    const update = (i: number, t: Partial<Threshold>): void =>
        onChange(value.map((x, j) => (j === i ? { ...x, ...t } : x)))
    const add = (): void => {
        const top = Math.max(0, ...value.map((t) => t.value))
        onChange([
            ...value,
            {
                value: value.length ? top + 10 : 0,
                color: THRESHOLD_COLORS[value.length % THRESHOLD_COLORS.length]![0],
            },
        ])
    }
    return (
        <div className="flex flex-col gap-1.5">
            {rows.length === 0 && (
                <div className="text-xs text-muted-foreground">
                    No thresholds yet. Add steps to color a value by how high it is.
                </div>
            )}
            {rows.map((t) => (
                <div key={t.i} className="flex items-center gap-2">
                    <span className="w-8 shrink-0 text-[11px] text-muted-foreground">
                        {t.i === rows.at(-1)!.i ? 'Base' : '≥'}
                    </span>
                    <NumberInput value={t.value} onChange={(v) => v !== undefined && update(t.i, { value: v })} />
                    <OptionSelect
                        className="h-8 w-28 shrink-0 text-xs"
                        aria-label="Threshold color"
                        options={THRESHOLD_COLORS}
                        value={t.color}
                        onChange={(color) => update(t.i, { color })}
                    />
                    <Button
                        variant="default"
                        size="icon-xs"
                        tooltip="Remove"
                        aria-label="Remove threshold"
                        onClick={() => onChange(value.length > 1 ? value.filter((_, j) => j !== t.i) : undefined)}
                    >
                        <IconTrash />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" className="self-start" onClick={add}>
                <IconPlus /> Add threshold
            </Button>
        </div>
    )
}

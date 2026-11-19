import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
    IconArrowLeft,
    IconBadge,
    IconBolt,
    IconChevronRight,
    IconCopy,
    IconDatabase,
    IconDocument,
    IconFilter,
    IconGraph,
    IconInfo,
    IconPerson,
    IconPulse,
    IconSearch,
    IconX,
} from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Input,
    Spinner,
    cn,
} from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { short } from '../charts/format'
import { Segmented } from '../editor/OptionsForm'
import { runQuery } from '../lib/api'
import { useDebounced } from '../lib/hooks'
import { useQuery, type QueryResult as Lookup } from '../lib/useQuery'
import {
    INTROSPECT_QUERIES,
    isFlagKey,
    newInsight,
    propCondition,
    selector,
    seriesCountsQuery,
    setInsightEvent,
    type Builder,
    type Filter,
    type LogCondition,
} from './build'
import { fetchOptions, ProjectScope, useProjectId } from './Builders'
import {
    Coverage,
    Heading,
    LoadingRows,
    propLabel,
    Stats,
    TYPE_ICON,
    useKeys,
    useTable,
    useValues,
    ValueBar,
    type KeyInfo,
} from './PropertyFilter'

type Source = 'events' | 'persons' | 'metrics' | 'logs'
type CondKind = 'event' | 'person' | 'label' | 'log'
type Cond = { kind: CondKind; key: string; value: string }
type Attr = { kind: CondKind; key: string; type?: KeyInfo['type'] }
export type Nav = { source: Source; entity?: string; conds: Cond[]; attr?: Attr }

export type IntrospectPick = {
    action: string
    describe: (nav: Nav) => string | undefined
    hint: string
    apply: (nav: Nav) => void
}

const SOURCES: [Source, string, typeof IconBolt][] = [
    ['events', 'Events', IconBolt],
    ['persons', 'Persons', IconPerson],
    ['metrics', 'Metrics', IconPulse],
    ['logs', 'Logs', IconDocument],
]
const ALL = ''

const CAVEATS: Record<Source, string> = {
    events: 'Event counts are the last 7 days, exact. Property shares are from a sample: the first 20,000 matching events of the last day (not random, not all of them). Narrowing shrinks the sample; its size is shown.',
    persons:
        'Shares are of the persons behind recent events, counted once per event (busy users weigh more): the last hour, or the last day once narrowed, up to 5,000 events.',
    metrics:
        'Metrics have no volume here. For a metric: how many values each label has, and per value how many series (label combinations) carried it in the last hour. Not samples or events.',
    logs: "Lines in the last hour, from PostHog's attribute index (no line is read). Shares: lines whose resource or line had the attribute. Narrowing by a log (not resource) attribute keeps whole resources that had it, so it's approximate.",
}

export function IntrospectDialog({
    projectId,
    onClose,
    start,
    search = '',
    pick,
}: {
    projectId: string
    onClose: () => void
    start?: Nav
    search?: string
    pick?: IntrospectPick
}): React.JSX.Element {
    const [nav, setNav] = useState<Nav>(start ?? { source: 'events', conds: [] })
    const [q, setQ] = useState(search)
    const place = `${nav.source}\n${nav.entity}\n${nav.attr?.key}`
    const [searchedAt, setSearchedAt] = useState(place)
    if (searchedAt !== place) {
        setSearchedAt(place)
        setQ('')
    }
    const [pointed, setPointed] = useState<string>()
    const [propTab, setPropTab] = useState<PropTab>()
    const level = nav.attr ? 'values' : nav.source === 'persons' || nav.entity !== undefined ? 'attrs' : 'entities'
    const up = (): void =>
        setNav((n) =>
            n.attr
                ? { ...n, attr: undefined }
                : n.conds.length
                  ? { ...n, conds: n.conds.slice(0, -1) }
                  : n.source !== 'persons'
                    ? { source: n.source, conds: [] }
                    : n
        )
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent
                size="full"
                className="flex h-[min(46rem,calc(100dvh-2rem))] flex-col gap-0"
                data-attr="dashboard-v2-introspect"
            >
                <ProjectScope value={projectId}>
                    <DialogHeader className="gap-2">
                        <DialogTitle className="flex items-center gap-2">
                            <IconDatabase className="size-4" /> Introspect
                        </DialogTitle>
                        <DialogDescription>
                            Everything this project has. Open anything to see what it carries and how often, and narrow
                            to a value to see the rest within it.
                        </DialogDescription>
                        {!pick && (
                            <Segmented
                                className="max-w-xl"
                                value={nav.source}
                                options={SOURCES.map(([s, l, I]) => [
                                    s,
                                    <span key={s} className="flex items-center gap-1.5">
                                        <I className="size-3.5" />
                                        {l}
                                    </span>,
                                ])}
                                onChange={(s) => setNav({ source: s as Source, conds: [] })}
                            />
                        )}
                        <Crumbs nav={nav} setNav={setNav} onUp={level !== 'entities' ? up : undefined} />
                    </DialogHeader>
                    <div className="min-h-0 flex-1 px-4 pb-4">
                        <div className="flex h-full flex-col overflow-hidden rounded-md border bg-card">
                            <div className="border-b p-2">
                                <div className="relative">
                                    <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                                    <Input
                                        autoFocus
                                        className="h-8 pl-7 text-xs"
                                        placeholder={
                                            level === 'entities'
                                                ? `Search ${nav.source === 'logs' ? 'services' : nav.source}…`
                                                : level === 'attrs'
                                                  ? `Search ${nav.source === 'metrics' ? 'labels' : nav.source === 'logs' ? 'attributes' : 'properties'}…`
                                                  : 'Search values…'
                                        }
                                        value={q}
                                        onChange={(e) => setQ(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Backspace' && !q && level !== 'entities' && up()}
                                        data-attr="dashboard-v2-introspect-search"
                                    />
                                </div>
                            </div>
                            <Caveat source={nav.source} />
                            <div className="min-h-0 flex-1">
                                {level === 'entities' ? (
                                    <Entities
                                        nav={nav}
                                        q={q}
                                        onOpen={(entity) => setNav({ ...nav, entity })}
                                        onActive={setPointed}
                                    />
                                ) : level === 'attrs' ? (
                                    <Attributes
                                        nav={nav}
                                        q={q}
                                        onOpen={(attr) => setNav({ ...nav, attr })}
                                        tab={propTab}
                                        onTab={setPropTab}
                                    />
                                ) : (
                                    <Values
                                        nav={nav}
                                        q={q}
                                        onNarrow={(value) =>
                                            setNav({
                                                ...nav,
                                                attr: undefined,
                                                conds: [
                                                    ...nav.conds.filter((c) => c.key !== nav.attr!.key),
                                                    { kind: nav.attr!.kind, key: nav.attr!.key, value },
                                                ],
                                            })
                                        }
                                    />
                                )}
                            </div>
                            {pick ? (
                                <PickActions
                                    nav={
                                        level === 'entities' && pointed !== undefined
                                            ? { ...nav, entity: pointed }
                                            : nav
                                    }
                                    pick={pick}
                                    onClose={onClose}
                                />
                            ) : (
                                <Actions nav={nav} />
                            )}
                        </div>
                    </div>
                </ProjectScope>
            </DialogContent>
        </Dialog>
    )
}

function Crumbs({ nav, setNav, onUp }: { nav: Nav; setNav: (n: Nav) => void; onUp?: () => void }): React.JSX.Element {
    const sourceLabel = SOURCES.find(([s]) => s === nav.source)![1]
    const parts: ReactNode[] = []
    if (nav.entity !== undefined) {
        parts.push(
            <button
                key="entity"
                type="button"
                className="cursor-pointer truncate font-medium hover:underline"
                onClick={() => setNav({ source: nav.source, entity: nav.entity, conds: [] })}
            >
                {nav.entity === ALL ? 'All services' : nav.entity}
            </button>
        )
    }
    nav.conds.forEach((c, i) =>
        parts.push(
            <span
                key={`c${i}`}
                className="flex items-center gap-1 rounded-md border bg-fill-selected py-0.5 pl-1.5 pr-0.5"
                data-attr="dashboard-v2-introspect-cond"
            >
                <span className="max-w-40 truncate">
                    {c.kind === 'label' || c.kind === 'log' ? c.key : propLabel(c.key)}
                </span>
                <span className="text-muted-foreground">=</span>
                <span className="max-w-40 truncate font-medium">{c.value}</span>
                <button
                    type="button"
                    className="cursor-pointer rounded p-0.5 hover:bg-fill-hover"
                    aria-label={`Stop narrowing to ${c.key} = ${c.value}`}
                    onClick={() => setNav({ ...nav, conds: nav.conds.filter((_, j) => j !== i), attr: undefined })}
                >
                    <IconX className="size-3" />
                </button>
            </span>
        )
    )
    if (nav.attr) {
        parts.push(
            <span key="attr" className="truncate font-medium">
                {nav.attr.kind === 'label' || nav.attr.kind === 'log' ? nav.attr.key : propLabel(nav.attr.key)}
            </span>
        )
    }
    return (
        <div className="flex min-h-7 flex-wrap items-center gap-1 text-xs" data-attr="dashboard-v2-introspect-crumbs">
            {onUp && (
                <Button variant="outline" size="xs" className="mr-1" onClick={onUp} aria-label="Up a level">
                    <IconArrowLeft className="size-3.5" />
                </Button>
            )}
            <button
                type="button"
                className="cursor-pointer text-muted-foreground hover:text-foreground hover:underline"
                onClick={() => setNav({ source: nav.source, conds: [] })}
            >
                {sourceLabel}
            </button>
            {parts.map((p, i) => (
                <span key={i} className="flex min-w-0 items-center gap-1">
                    <IconChevronRight className="size-3 shrink-0 text-muted-foreground" />
                    {p}
                </span>
            ))}
        </div>
    )
}

function Caveat({ source }: { source: Source }): React.JSX.Element {
    return (
        <div
            className="flex items-start gap-1.5 border-b bg-muted px-3 py-1.5 text-[11px] text-muted-foreground"
            title={CAVEATS[source]}
            data-attr="dashboard-v2-introspect-caveat"
        >
            <IconInfo className="mt-px size-3 shrink-0" />
            <span className="line-clamp-2">{CAVEATS[source]}</span>
        </div>
    )
}

type Row = {
    id: string
    icon: ReactNode
    label: string
    sub?: string
    right?: ReactNode
    kind?: CondKind
    data?: unknown
}
type Section = { title?: ReactNode; rows: Row[]; status?: ReactNode }

function ListWithDetails({
    sections,
    onOpen,
    details,
    empty,
    onActive,
}: {
    sections: Section[]
    onOpen: (row: Row) => void
    details?: (row: Row) => ReactNode
    empty?: ReactNode
    onActive?: (row: Row | undefined) => void
}): React.JSX.Element {
    const rows = sections.flatMap((s) => s.rows)
    const [active, setActive] = useState(0)
    const current = rows[Math.min(active, rows.length - 1)]
    useEffect(() => onActive?.(current), [current?.id])
    const shownId = useDebounced(current?.id, 150)
    const shown = rows.find((r) => r.id === shownId)
    const ref = useRef<HTMLDivElement>(null)
    const ids = rows.map((r) => r.id).join('\n')
    useEffect(() => setActive(0), [ids])
    useEffect(() => {
        ref.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
    }, [active])
    useEffect(() => {
        const h = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((a) => Math.max(0, Math.min(rows.length - 1, a + (e.key === 'ArrowDown' ? 1 : -1))))
            } else if (e.key === 'Enter' && current && (e.target as HTMLElement).tagName === 'INPUT') {
                e.preventDefault()
                onOpen(current)
            }
        }
        window.addEventListener('keydown', h)
        return () => window.removeEventListener('keydown', h)
    })
    let i = 0
    return (
        <div className="flex h-full min-h-0">
            <div
                ref={ref}
                role="listbox"
                className="min-h-0 min-w-0 flex-1 overflow-auto p-1"
                data-attr="dashboard-v2-introspect-list"
            >
                {sections.map((s, si) => (
                    <section key={si}>
                        {s.title && <Heading>{s.title}</Heading>}
                        {s.rows.map((r) => {
                            const idx = i++
                            return (
                                <button
                                    key={r.id}
                                    type="button"
                                    role="option"
                                    aria-selected={idx === active}
                                    data-active={idx === active}
                                    className={cn(
                                        'group flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-fill-hover',
                                        idx === active && 'bg-muted'
                                    )}
                                    onMouseEnter={() => setActive(idx)}
                                    onFocus={() => setActive(idx)}
                                    onClick={() => onOpen(r)}
                                >
                                    <span className="shrink-0 text-muted-foreground [&>svg]:size-3.5">{r.icon}</span>
                                    <span className="flex min-w-0 flex-1 flex-col">
                                        <span className="truncate font-medium">{r.label}</span>
                                        {r.sub && (
                                            <span className="truncate font-mono text-[10px] text-muted-foreground">
                                                {r.sub}
                                            </span>
                                        )}
                                    </span>
                                    {r.right}
                                    <IconChevronRight className="size-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
                                </button>
                            )
                        })}
                        {s.status}
                    </section>
                ))}
                {!rows.length && !sections.some((s) => s.status) && (
                    <div className="px-2 py-3 text-xs text-muted-foreground">{empty ?? 'Nothing here'}</div>
                )}
            </div>
            {details && (
                <div className="w-80 shrink-0 overflow-auto border-l" data-attr="dashboard-v2-introspect-details">
                    {shown ? (
                        details(shown)
                    ) : (
                        <div className="p-3 text-xs text-muted-foreground">Point at a row for more</div>
                    )}
                </div>
            )}
        </div>
    )
}

const Count = ({ n, unit }: { n: number; unit: string }): React.JSX.Element => (
    <span className="shrink-0 tabular-nums text-muted-foreground" title={`${n.toLocaleString()} ${unit}`}>
        {short(n)} <span className="opacity-70">{unit}</span>
    </span>
)
const Loading = ({ what }: { what: string }): React.JSX.Element => (
    <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
        <Spinner className="size-3.5" /> {what}…
    </div>
)
const Failed = ({ error }: { error: unknown }): React.JSX.Element | null =>
    error ? (
        <div className="px-2 py-2 text-xs text-destructive-foreground">{String((error as Error).message ?? error)}</div>
    ) : null
const matches = (q: string, ...texts: (string | undefined)[]): boolean => {
    const s = q.trim().toLowerCase()
    return !s || texts.some((t) => t?.toLowerCase().includes(s))
}

function Entities({
    nav,
    q,
    onOpen,
    onActive,
}: {
    nav: Nav
    q: string
    onOpen: (entity: string) => void
    onActive?: (entity: string | undefined) => void
}): React.JSX.Element {
    const events = useTable(nav.source === 'events' ? INTROSPECT_QUERIES.events() : undefined)
    const services = useTable(nav.source === 'logs' ? INTROSPECT_QUERIES.logServices() : undefined)
    const metrics = useMetricNames(nav.source === 'metrics', q)
    if (nav.source === 'metrics') {
        const rows = (metrics.data ?? [])
            .filter((m) => matches(q, m))
            .map((m): Row => ({ id: m, icon: <IconPulse />, label: m }))
        return (
            <ListWithDetails
                sections={[
                    {
                        title: metrics.total ? `${short(metrics.total)} metrics` : undefined,
                        rows,
                        status: metrics.isLoading ? (
                            <Loading what="Finding metrics" />
                        ) : (
                            <Failed error={metrics.error} />
                        ),
                    },
                ]}
                onOpen={(r) => onOpen(r.id)}
                onActive={(r) => onActive?.(r?.id)}
                details={(r) => <MetricPreview metric={r.id} />}
                empty="No metrics in the last hour"
            />
        )
    }
    const t = nav.source === 'events' ? events : services
    const all = (t.data ?? []).map((r) => ({ name: String(r.entity), n: Number(r.n) }))
    const total = all.reduce((a, x) => a + x.n, 0)
    const rows = all
        .filter((x) => matches(q, x.name))
        .map(
            (x): Row => ({
                id: x.name,
                icon: nav.source === 'events' ? <IconBolt /> : <IconDocument />,
                label: x.name,
                right: (
                    <span className="flex items-center gap-2">
                        <Coverage share={total ? x.n / total : 0} />
                        <Count n={x.n} unit={nav.source === 'events' ? 'events' : 'lines'} />
                    </span>
                ),
            })
        )
    const allServices: Row[] =
        nav.source === 'logs' && matches(q, 'all services')
            ? [
                  {
                      id: ALL,
                      icon: <IconDocument />,
                      label: 'All services',
                      right: total ? <Count n={total} unit="lines" /> : undefined,
                  },
              ]
            : []
    return (
        <ListWithDetails
            sections={[
                {
                    title: all.length
                        ? `${short(all.length)} ${nav.source === 'events' ? 'events · last 7 days' : 'services · last hour'}`
                        : undefined,
                    rows: [...allServices, ...rows],
                    status: t.isLoading ? <Loading what={`Counting ${nav.source}`} /> : <Failed error={t.error} />,
                },
            ]}
            onOpen={(r) => onOpen(r.id)}
            onActive={(r) => onActive?.(r?.id)}
            details={(r) =>
                nav.source === 'events' ? (
                    <AttrPreview title={r.label} nav={{ source: 'events', entity: r.id, conds: [] }} />
                ) : (
                    <AttrPreview title={r.label} nav={{ source: 'logs', entity: r.id, conds: [] }} />
                )
            }
            empty={q ? `Nothing matches “${q.trim()}”` : 'No data in range'}
        />
    )
}

type PropTab = 'event' | 'person' | 'flags' | 'unseen'
const TAB_LABEL: Record<PropTab, string> = { event: 'Event', person: 'Person', flags: 'Flags', unseen: 'Not seen' }
const TAB_NOTE: Partial<Record<PropTab, string>> = {
    flags: "One property per feature flag ($feature/<flag> = its variant), set on events once flags are evaluated: kept apart so they don't bury the rest.",
    unseen: "Defined in PostHog, but none of the sampled events had them: nothing says they're sent with this event (they may be rare, or other events').",
}
type Group = { kind: 'event' | 'person'; keys: KeyInfo[]; title?: string; status?: ReactNode }

function useAttributeSections(
    nav: Nav,
    q: string,
    limit = Infinity,
    tab?: PropTab
): {
    sections: Section[]
    sampleSize?: number
    recomputing?: boolean
    tabs?: { id: PropTab; n: number; loading: boolean }[]
    tab?: PropTab
} {
    const isEvents = nav.source === 'events'
    const events = isEvents ? [nav.entity ?? null] : []
    const scope = {
        conds: nav.conds
            .filter((c) => c.kind === 'event' || c.kind === 'person')
            .map((c) => propCondition(c.kind as 'event' | 'person', c.key, c.value)),
    }
    const eventKeys = useKeys('event', events, q, isEvents, scope)
    const personKeys = useKeys('person', events, q, isEvents || nav.source === 'persons', scope)
    const labels = useMetricLabels(nav.source === 'metrics' ? nav.entity : undefined, metricFilters(nav))
    const logs = useTable(
        nav.source === 'logs' && nav.entity !== undefined
            ? INTROSPECT_QUERIES.logKeys(nav.entity || undefined, logConds(nav))
            : undefined,
        `log-keys:${nav.entity}`
    )
    const found = (keys: KeyInfo[]): KeyInfo[] => keys.filter((k) => matches(q, k.key, propLabel(k.key)))
    const propRows = (keys: KeyInfo[], kind: 'event' | 'person'): Row[] =>
        found(keys)
            .slice(0, limit)
            .map((k): Row => {
                const Icon = TYPE_ICON[k.type]
                const label = propLabel(k.key)
                return {
                    id: `${kind}:${k.key}`,
                    icon: <Icon />,
                    label,
                    sub: label !== k.key ? k.key : undefined,
                    right: k.share !== undefined ? <Coverage share={k.share} /> : undefined,
                    kind,
                    data: k,
                }
            })
    const keysStatus = (k: ReturnType<typeof useKeys>, what: string): React.JSX.Element =>
        k.isLoading && !k.keys.length ? (
            <Loading what={`Sampling ${what}`} />
        ) : (
            <Failed error={!k.keys.length && k.error} />
        )
    if (nav.source === 'events' || nav.source === 'persons') {
        const seen = (k: ReturnType<typeof useKeys>): KeyInfo[] =>
            k.keys.filter((x) => x.share !== undefined && !isFlagKey(x.key))
        const unseen = (k: ReturnType<typeof useKeys>): KeyInfo[] =>
            k.keys.filter((x) => x.share === undefined && !isFlagKey(x.key))
        const both = <T,>(a: T[], b: T[]): T[] => (isEvents ? [...a, ...b] : b)
        const groups: Record<PropTab, Group[]> = {
            event: isEvents
                ? [{ kind: 'event', keys: seen(eventKeys), status: keysStatus(eventKeys, 'event properties') }]
                : [],
            person: [
                {
                    kind: 'person',
                    keys: seen(personKeys),
                    title: isEvents ? "Of these events' persons" : undefined,
                    status: keysStatus(personKeys, 'person properties'),
                },
            ],
            flags: both(
                [{ kind: 'event' as const, keys: eventKeys.flags, title: 'On the events' }],
                [{ kind: 'person' as const, keys: personKeys.flags, title: 'On their persons' }]
            ),
            unseen: both(
                [{ kind: 'event' as const, keys: unseen(eventKeys), title: 'Event properties' }],
                [{ kind: 'person' as const, keys: unseen(personKeys), title: 'Person properties' }]
            ),
        }
        const loading = { event: eventKeys.isLoading, person: personKeys.isLoading }
        const tabs = (Object.keys(groups) as PropTab[])
            .filter(
                (id) =>
                    groups[id].length && (id === 'event' || id === 'person' || groups[id].some((g) => g.keys.length))
            )
            .map((id) => ({
                id,
                n: groups[id].reduce((a, g) => a + found(g.keys).length, 0),
                loading: groups[id].some((g) => loading[g.kind]),
            }))
        const chosen = tabs.find((t) => t.id === tab) ?? tabs[0]!
        const active = q.trim() && !chosen.n ? (tabs.find((t) => t.n)?.id ?? chosen.id) : chosen.id
        const sectionsOf = (gs: Group[], titled: boolean): Section[] =>
            gs
                .filter((g) => g.keys.length || g.status)
                .map((g) => ({
                    title: titled && g.title ? <SectionTitle text={g.title} n={found(g.keys).length} /> : undefined,
                    rows: propRows(g.keys, g.kind),
                    status: g.status,
                }))
        return {
            sampleSize: (isEvents ? eventKeys : personKeys).sampleSize,
            recomputing: eventKeys.recomputing || personKeys.recomputing,
            ...(tab === undefined && isEvents
                ? {
                      sections: [
                          {
                              title: 'Event properties',
                              rows: propRows(seen(eventKeys), 'event'),
                              status: groups.event[0]!.status,
                          },
                          {
                              title: 'Person properties',
                              rows: propRows(seen(personKeys), 'person'),
                              status: groups.person[0]!.status,
                          },
                      ],
                  }
                : {
                      tabs,
                      tab: active,
                      sections: sectionsOf(
                          groups[active],
                          groups[active].filter((g) => g.keys.length).length > 1 || active === 'person'
                      ),
                  }),
        }
    }
    if (nav.source === 'metrics') {
        const rows = (labels.data ?? [])
            .filter((l) => matches(q, l.key))
            .slice(0, limit)
            .map(
                (l): Row => ({
                    id: `label:${l.key}`,
                    icon: <IconBadge />,
                    label: l.key,
                    right: <Count n={l.values} unit={l.values >= 500 ? 'values+' : 'values'} />,
                    kind: 'label',
                    data: l,
                })
            )
        return {
            sections: [
                {
                    title: <SectionTitle text="Labels" n={labels.data?.length ?? 0} />,
                    rows,
                    status: labels.isLoading ? <Loading what="Reading labels" /> : <Failed error={labels.error} />,
                },
            ],
        }
    }
    const total = Number(logs.data?.[0]?.total ?? 0)
    const logRows = (resource: boolean): Row[] =>
        (logs.data ?? [])
            .filter((r) => !!Number(r.resource) === resource && matches(q, String(r.prop_key)))
            .slice(0, limit)
            .map(
                (r): Row => ({
                    id: `log:${r.prop_key}`,
                    icon: <IconBadge />,
                    label: String(r.prop_key),
                    right: total ? <Coverage share={Math.min(1, Number(r.n) / total)} /> : undefined,
                    kind: 'log',
                    data: r,
                })
            )
    const level: Row[] = matches(q, 'level', 'severity')
        ? [{ id: 'log:severity_text', icon: <IconBadge />, label: 'Level', sub: 'severity_text', kind: 'log' }]
        : []
    const status = logs.isLoading ? <Loading what="Reading the attribute index" /> : <Failed error={logs.error} />
    return {
        sampleSize: total || undefined,
        recomputing: logs.isPlaceholderData,
        sections: [
            { title: 'Line', rows: level },
            {
                title: <SectionTitle text="Resource attributes" n={logRows(true).length} />,
                rows: logRows(true),
                status,
            },
            { title: <SectionTitle text="Log attributes" n={logRows(false).length} />, rows: logRows(false) },
        ],
    }
}
const SectionTitle = ({ text, n }: { text: string; n: number }): React.JSX.Element => (
    <span className="flex items-center gap-1.5">
        {text}
        {n > 0 && <span className="font-normal normal-case tabular-nums">{short(n)}</span>}
    </span>
)
const metricFilters = (nav: Nav): Filter[] =>
    nav.conds.filter((c) => c.kind === 'label').map((c) => ({ key: c.key, op: '=', value: c.value }))
const logConds = (nav: Nav): LogCondition[] =>
    nav.conds.filter((c) => c.kind === 'log').map((c) => ({ key: c.key, value: c.value }))
const attrOf = (r: Row): Attr => ({
    kind: r.kind!,
    key: r.kind === 'event' || r.kind === 'person' ? (r.data as KeyInfo).key : r.id.slice(r.id.indexOf(':') + 1),
    type: r.kind === 'event' || r.kind === 'person' ? (r.data as KeyInfo).type : undefined,
})

function Attributes({
    nav,
    q,
    onOpen,
    tab,
    onTab,
}: {
    nav: Nav
    q: string
    onOpen: (a: Attr) => void
    tab?: PropTab
    onTab: (t: PropTab) => void
}): React.JSX.Element {
    const {
        sections,
        sampleSize,
        recomputing,
        tabs,
        tab: active,
    } = useAttributeSections(nav, q, Infinity, tab ?? 'event')
    const note = active && TAB_NOTE[active]
    return (
        <div className="flex h-full flex-col">
            {tabs && tabs.length > 1 && (
                <div className="px-2 pt-2">
                    <Segmented
                        value={active!}
                        options={tabs.map((t) => [
                            t.id,
                            <span key={t.id} className="flex items-center gap-1.5">
                                {TAB_LABEL[t.id]}
                                <span className="tabular-nums text-muted-foreground">
                                    {t.loading && !t.n ? '…' : short(t.n)}
                                </span>
                            </span>,
                        ])}
                        onChange={(t) => onTab(t as PropTab)}
                    />
                </div>
            )}
            {note && <div className="px-3 pt-1.5 text-[11px] text-muted-foreground">{note}</div>}
            {recomputing ? (
                <div className="flex items-center gap-1.5 px-3 pt-1.5 text-[11px] text-muted-foreground">
                    <Spinner className="size-3" /> Recomputing for the narrowed sample; the numbers below are from
                    before
                </div>
            ) : (
                sampleSize !== undefined && <SampleSize nav={nav} n={sampleSize} />
            )}
            <div className={cn('min-h-0 flex-1 transition-opacity', recomputing && 'opacity-50')}>
                <ListWithDetails
                    sections={sections}
                    onOpen={(r) => onOpen(attrOf(r))}
                    details={(r) => <ValuesPreview nav={nav} attr={attrOf(r)} />}
                    empty={q ? `Nothing matches “${q.trim()}”` : 'Nothing recorded in range'}
                />
            </div>
        </div>
    )
}

function SampleSize({ nav, n }: { nav: Nav; n: number }): React.JSX.Element {
    const unit = nav.source === 'logs' ? 'lines' : 'events'
    return (
        <div
            className={cn('px-3 pt-1.5 text-[11px]', n < 200 ? 'text-warning-foreground' : 'text-muted-foreground')}
            data-attr="dashboard-v2-introspect-sample"
        >
            Computed from {n.toLocaleString()} {unit}
            {n >= 20_000 && nav.source !== 'logs' ? ' (the sample cap)' : ''}
            {n < 200 ? ': a small sample, so the shares are rough' : ''}
        </div>
    )
}

function AttrPreview({ title, nav }: { title: string; nav: Nav }): React.JSX.Element {
    const { sections } = useAttributeSections(nav, '', 8)
    return (
        <div className="flex flex-col gap-1 p-3 text-xs">
            <span className="font-semibold">{title}</span>
            {sections.map((s, i) =>
                s.rows.length || s.status ? (
                    <div key={i} className="flex flex-col">
                        {s.title && <Heading>{s.title}</Heading>}
                        {s.rows.map((r) => (
                            <div key={r.id} className="flex items-center gap-2 py-0.5">
                                <span className="text-muted-foreground [&>svg]:size-3">{r.icon}</span>
                                <span className="min-w-0 flex-1 truncate">{r.label}</span>
                                {r.right}
                            </div>
                        ))}
                        {s.status}
                    </div>
                ) : null
            )}
        </div>
    )
}

function MetricPreview({ metric }: { metric: string }): React.JSX.Element {
    const labels = useMetricLabels(metric, [])
    return (
        <div className="flex flex-col gap-1 p-3 text-xs">
            <span className="break-all font-mono font-semibold">{metric}</span>
            <Heading>Labels</Heading>
            {labels.isLoading && <LoadingRows />}
            {(labels.data ?? []).slice(0, 12).map((l) => (
                <div key={l.key} className="flex items-center gap-2 py-0.5">
                    <IconBadge className="size-3 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{l.key}</span>
                    <Count n={l.values} unit="values" />
                </div>
            ))}
        </div>
    )
}

type ValueRow = { value: string; n: number; share: number }
function useValueRows(
    nav: Nav,
    attr: Attr,
    q: string
): {
    rows: ValueRow[]
    stats?: { min: number; median: number; max: number; mean: number }
    isLoading: boolean
    error: Error | null
    unit: string
} {
    const isProp = attr.kind === 'event' || attr.kind === 'person'
    const events = nav.source === 'events' ? [nav.entity ?? null] : []
    const scope = {
        conds: nav.conds
            .filter((c) => c.kind === 'event' || c.kind === 'person')
            .map((c) => propCondition(c.kind as 'event' | 'person', c.key, c.value)),
    }
    const props = useValues(
        attr.kind === 'person' ? 'person' : 'event',
        isProp ? attr.key : undefined,
        attr.type,
        events,
        q,
        scope
    )
    const metric = useMetricValues(attr.kind === 'label' ? nav.entity : undefined, metricFilters(nav), attr.key)
    const logs = useTable(
        attr.kind === 'log'
            ? INTROSPECT_QUERIES.logValues(nav.entity || undefined, attr.key, logConds(nav), q)
            : undefined
    )
    if (isProp) {
        return {
            rows: props.values as ValueRow[],
            stats: props.stats,
            isLoading: props.isLoading,
            error: props.error,
            unit: 'events',
        }
    }
    if (attr.kind === 'label') {
        const rows = (metric.data ?? []).filter((v) => matches(q, v.value))
        return { rows, isLoading: metric.isLoading, error: metric.error, unit: 'series' }
    }
    const rows = (logs.data ?? []).map((r) => ({
        value: String(r.prop_value),
        n: Number(r.n),
        share: Number(r.total) ? Math.min(1, Number(r.n) / Number(r.total)) : 0,
    }))
    return { rows, isLoading: logs.isLoading, error: logs.error, unit: 'lines' }
}

function Values({ nav, q, onNarrow }: { nav: Nav; q: string; onNarrow: (value: string) => void }): React.JSX.Element {
    const attr = nav.attr!
    const v = useValueRows(nav, attr, q)
    return (
        <div className="flex h-full flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
                <IconFilter className="size-3" /> Click a value to narrow to it: everything recomputes within it.
                {v.stats && (
                    <span className="ml-auto w-72">
                        <Stats stats={v.stats} />
                    </span>
                )}
            </div>
            <div className="min-h-0 flex-1">
                <ListWithDetails
                    sections={[
                        {
                            rows: v.rows.map(
                                (x): Row => ({
                                    id: x.value,
                                    icon: <IconGraph />,
                                    label: x.value,
                                    right: (
                                        <span className="flex items-center gap-2">
                                            <Coverage share={x.share} />
                                            <Count n={x.n} unit={v.unit} />
                                        </span>
                                    ),
                                })
                            ),
                            status: v.isLoading ? <Loading what="Counting values" /> : <Failed error={v.error} />,
                        },
                    ]}
                    onOpen={(r) => onNarrow(r.id)}
                    details={(r) => (
                        <div className="flex flex-col gap-2 p-3 text-xs">
                            <span className="break-all font-semibold">{r.label}</span>
                            <span className="text-muted-foreground">
                                Narrow to it to see the other{' '}
                                {nav.source === 'metrics'
                                    ? 'labels'
                                    : nav.source === 'logs'
                                      ? 'attributes'
                                      : 'properties'}{' '}
                                within it.
                            </span>
                            <Heading>Top values</Heading>
                            {v.rows.slice(0, 10).map((x) => (
                                <ValueBar key={x.value} value={x.value} share={x.share} n={x.n} />
                            ))}
                        </div>
                    )}
                    empty={q ? `No value matches “${q.trim()}”` : 'No values in range'}
                />
            </div>
        </div>
    )
}

function ValuesPreview({ nav, attr }: { nav: Nav; attr: Attr }): React.JSX.Element {
    const v = useValueRows(nav, attr, '')
    return (
        <div className="flex flex-col gap-2 p-3 text-xs">
            <span className="font-semibold">
                {attr.kind === 'label' || attr.kind === 'log' ? attr.key : propLabel(attr.key)}
            </span>
            {v.stats && <Stats stats={v.stats} />}
            <Heading>Top values</Heading>
            {v.isLoading && <LoadingRows />}
            {!v.isLoading && !v.rows.length && <span className="text-muted-foreground">No values in range</span>}
            {v.rows.slice(0, 10).map((x) => (
                <ValueBar key={x.value} value={x.value} share={x.share} n={x.n} />
            ))}
        </div>
    )
}

function useMetricNames(
    enabled: boolean,
    q: string
): { data: string[] | undefined; total: number | undefined; isLoading: boolean; error: Error | null } {
    const projectId = useProjectId()
    const typed = useDebounced(q.trim(), 250)
    const first = useQuery({
        queryKey: ['introspect-metrics', projectId],
        enabled,
        staleTime: 5 * 60_000,
        queryFn: () => fetchOptions(projectId, 'promql', 'label_values(__name__)'),
    })
    const capped = (first.data?.total ?? 0) > (first.data?.options.length ?? 0)
    const found = useQuery({
        queryKey: ['introspect-metrics', projectId, typed],
        enabled: enabled && capped && !!typed,
        staleTime: 5 * 60_000,
        queryFn: () => fetchOptions(projectId, 'promql', 'label_values(__name__)', typed),
    })
    return {
        data: capped && typed ? found.data?.options : first.data?.options,
        total: first.data?.total,
        isLoading: first.isLoading || (capped && !!typed && found.isLoading),
        error: first.error,
    }
}

const quoteLabel = (l: string): string => (/^[A-Za-z_]\w*$/.test(l) ? l : `"${l}"`)
function useMetricLabels(metric: string | undefined, filters: Filter[]): Lookup<{ key: string; values: number }[]> {
    const projectId = useProjectId()
    const sel = metric ? selector(metric, filters) : ''
    return useQuery({
        queryKey: ['introspect-labels', projectId, sel],
        enabled: !!metric,
        staleTime: 5 * 60_000,
        queryFn: async () => {
            const names = (await fetchOptions(projectId, 'promql', `label_names(${sel})`)).options.slice(0, 40)
            const values = await Promise.all(
                names.map((l) =>
                    fetchOptions(projectId, 'promql', `label_values(${sel}, ${quoteLabel(l)})`).catch(() => ({
                        options: [],
                        total: 0,
                    }))
                )
            )
            return names
                .map((key, i) => ({ key, values: values[i]!.total ?? values[i]!.options.length }))
                .sort((a, b) => b.values - a.values)
        },
    })
}

function useMetricValues(metric: string | undefined, filters: Filter[], label: string): Lookup<ValueRow[]> {
    const projectId = useProjectId()
    const query = metric ? seriesCountsQuery({ metric, filters }, label, 50) : undefined
    return useQuery({
        queryKey: ['introspect-label-values', projectId, query],
        enabled: !!query,
        staleTime: 5 * 60_000,
        queryFn: async ({ signal }): Promise<ValueRow[]> => {
            const r = await runQuery({
                signal,
                projectId,
                target: { refId: 'I', language: 'promql', instant: true, query: query! },
                time: { from: 'now-1h', to: 'now' },
                variables: {},
            })
            if (r.error) {
                throw new Error(r.error)
            }
            const rows = r.frames
                .map((f) => {
                    const v = f.fields.find((x) => x.labels) ?? f.fields.at(-1)
                    return { value: v?.labels?.[label] ?? '', n: Math.round(Number(v?.values[0] ?? 0)) }
                })
                .filter((x) => x.value)
                .sort((a, b) => b.n - a.n)
            const total = rows.reduce((a, x) => a + x.n, 0)
            return rows.map((x) => ({ ...x, share: total ? x.n / total : 0 }))
        },
    })
}

export function introspectBuilder(nav: Nav): Builder | undefined {
    const attr = nav.attr
    if (nav.source === 'events' || nav.source === 'persons') {
        const event = nav.source === 'events' ? (nav.entity ?? null) : null
        return {
            source: 'events',
            insight: {
                query: {
                    ...newInsight('TrendsQuery', [event]),
                    ...(nav.conds.length
                        ? {
                              properties: nav.conds.map((c) => ({
                                  key: c.key,
                                  value: [c.value],
                                  operator: 'exact',
                                  type: c.kind,
                              })),
                          }
                        : {}),
                    ...(attr && (attr.kind === 'event' || attr.kind === 'person')
                        ? { breakdownFilter: { breakdown: attr.key, breakdown_type: attr.kind } }
                        : {}),
                },
            },
        }
    }
    if (nav.source === 'metrics' && nav.entity) {
        return {
            source: 'metrics',
            metric: nav.entity,
            filters: metricFilters(nav),
            ...(attr ? { by: [attr.key] } : {}),
        }
    }
    if (nav.source === 'logs' && nav.entity !== undefined) {
        const levels = nav.conds.filter((c) => c.key === 'severity_text').map((c) => c.value)
        return {
            source: 'logs',
            ...(nav.entity ? { services: [nav.entity] } : {}),
            ...(levels.length ? { levels } : {}),
            filters: nav.conds
                .filter((c) => c.key !== 'severity_text')
                .map((c) => ({ key: c.key, op: '=', value: c.value, resource: true })),
            ...(attr ? { mode: 'group' as const, groupBy: [attr.key] } : {}),
        }
    }
    return undefined
}

const subject = (nav: Nav): string =>
    nav.source === 'logs'
        ? `${nav.entity || 'all services'} logs`
        : nav.source === 'metrics'
          ? (nav.entity ?? '')
          : nav.source === 'persons' || !nav.entity
            ? 'all events'
            : nav.entity

export const describeNav = (nav: Nav): string =>
    `${subject(nav)}${nav.conds.length ? ` where ${nav.conds.map((c) => `${c.key} = ${c.value}`).join(', ')}` : ''}${
        nav.attr
            ? ` by ${nav.attr.kind === 'label' || nav.attr.kind === 'log' ? nav.attr.key : propLabel(nav.attr.key)}`
            : ''
    }`

export function useIntrospectPicker(projectId: string): {
    open: (start: Nav, pick: IntrospectPick) => (search: string) => void
    dialog: React.JSX.Element | undefined
} {
    const [at, setAt] = useState<{ start: Nav; search: string; pick: IntrospectPick }>()
    return {
        open: (start: Nav, pick: IntrospectPick) => (search: string) => setAt({ start, search, pick }),
        dialog: at && (
            <IntrospectDialog
                projectId={projectId}
                start={at.start}
                search={at.search}
                pick={at.pick}
                onClose={() => setAt(undefined)}
            />
        ),
    }
}

function PickActions({
    nav,
    pick,
    onClose,
}: {
    nav: Nav
    pick: IntrospectPick
    onClose: () => void
}): React.JSX.Element {
    const said = pick.describe(nav)
    return (
        <div className="flex items-center gap-2 border-t bg-muted px-3 py-2.5 text-xs">
            <span
                className={cn('min-w-0 flex-1 truncate', said ? 'font-medium' : 'text-muted-foreground')}
                data-attr="dashboard-v2-introspect-pick-summary"
            >
                {said ?? pick.hint}
            </span>
            <div className="flex gap-2">
                <Button variant="outline" onClick={onClose}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    disabled={!said}
                    data-attr="dashboard-v2-introspect-use"
                    onClick={() => {
                        pick.apply(nav)
                        onClose()
                    }}
                >
                    {pick.action}
                </Button>
            </div>
        </div>
    )
}

export function introspectNav(b: Builder): Nav | undefined {
    const eq = (fs: Filter[] = []): Filter[] => fs.filter((f) => f.op === '=' && !f.values?.length)
    if (b.source === 'metrics') {
        return {
            source: 'metrics',
            entity: b.metric,
            conds: b.metric ? eq(b.filters).map((f) => ({ kind: 'label', key: f.key, value: f.value })) : [],
            attr: b.metric && b.by?.[0] ? { kind: 'label', key: b.by[0] } : undefined,
        }
    }
    if (b.source === 'logs') {
        return {
            source: 'logs',
            entity: b.services?.length === 1 ? b.services[0] : ALL,
            conds: [
                ...(b.levels?.length === 1
                    ? [{ kind: 'log' as const, key: 'severity_text', value: b.levels[0]! }]
                    : []),
                ...eq(b.filters).map((f) => ({ kind: 'log' as const, key: f.key, value: f.value })),
            ],
            attr: b.mode === 'group' && b.groupBy?.[0] ? { kind: 'log', key: b.groupBy[0] } : undefined,
        }
    }
    const q = b.source === 'events' ? b.insight?.query : undefined
    if (q?.kind !== 'TrendsQuery') {
        return undefined
    }
    const s0 = q.series?.[0]
    const bd = q.breakdownFilter
    return {
        source: 'events',
        entity: s0?.kind === 'EventsNode' && s0.event ? s0.event : undefined,
        conds: (Array.isArray(q.properties) ? q.properties : []).filter(exactProp).map((f: any) => ({
            kind: f.type,
            key: f.key,
            value: String(Array.isArray(f.value) ? f.value[0] : f.value),
        })),
        attr:
            typeof bd?.breakdown === 'string' && (bd.breakdown_type === 'event' || bd.breakdown_type === 'person')
                ? { kind: bd.breakdown_type, key: bd.breakdown }
                : undefined,
    }
}
const exactProp = (f: any): boolean =>
    (f?.type === 'event' || f?.type === 'person') &&
    (f.operator ?? 'exact') === 'exact' &&
    (!Array.isArray(f.value) || f.value.length === 1)

export function applyNav(b: Builder, nav: Nav): Builder {
    const made = introspectBuilder(nav)
    if (made?.source === 'metrics' && b.source === 'metrics') {
        const same = made.metric === b.metric
        return {
            ...b,
            metric: made.metric,
            filters: [
                ...(same ? (b.filters ?? []).filter((f) => f.op !== '=' || f.values?.length) : []),
                ...(made.filters ?? []),
            ],
            by: made.by ?? (same ? b.by : undefined),
        }
    }
    if (made?.source === 'logs' && b.source === 'logs') {
        return {
            ...b,
            services: made.services ?? (nav.entity === ALL && (b.services?.length ?? 0) > 1 ? b.services : undefined),
            levels: made.levels ?? ((b.levels?.length ?? 0) > 1 ? b.levels : undefined),
            filters: [...(b.filters ?? []).filter((f) => f.op !== '='), ...(made.filters ?? [])],
            ...(made.mode ? { mode: made.mode, groupBy: made.groupBy } : {}),
        }
    }
    if (made?.source === 'events' && b.source === 'events' && b.insight) {
        const q = b.insight.query
        const m = made.insight!.query
        return {
            ...b,
            insight: {
                ...b.insight,
                query: {
                    ...setInsightEvent(q, 0, nav.entity ?? null),
                    properties: [
                        ...(Array.isArray(q.properties) ? q.properties : []).filter((f: any) => !exactProp(f)),
                        ...(m.properties ?? []),
                    ],
                    ...(m.breakdownFilter ? { breakdownFilter: m.breakdownFilter } : {}),
                },
            },
        }
    }
    return made ?? b
}

function Actions({ nav }: { nav: Nav }): React.JSX.Element {
    const name = nav.attr?.key ?? nav.entity
    return (
        <div className="flex items-center gap-2 border-t bg-muted px-3 py-2.5 text-xs">
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
                {name ? describeNav(nav) : 'Open something to see what it carries'}
            </span>
            {name && (
                <Button variant="outline" onClick={() => void copyToClipboard(name, 'name')}>
                    <IconCopy className="size-3.5" /> Copy name
                </Button>
            )}
        </div>
    )
}

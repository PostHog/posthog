import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
    IconArrowLeft,
    IconBolt,
    IconCalculator,
    IconCalendar,
    IconCheck,
    IconLetter,
    IconPeople,
    IconPerson,
    IconPlus,
    IconSearch,
    IconStack,
    IconTelescope,
    IconToggle,
    IconX,
} from '@posthog/icons'
import {
    Button,
    Checkbox,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Input,
    Spinner,
    cn,
} from '@posthog/quill'

import { compactNumber } from 'lib/utils/numbers'

import type { DataFrame } from '../charts/frame'
import { Segmented } from '../editor/OptionsForm'
import { runQuery } from '../lib/api'
import { pushRecent, readStored, useDebounced } from '../lib/hooks'
import { keepPreviousData, useQuery, useQueryClient, type QueryResult as Lookup } from '../lib/useQuery'
import { isFlagKey, actionPick, PROPERTY_QUERIES, type PropKind } from './build'
import { useProjectId } from './Builders'
import { IntrospectDialog, type Nav } from './Introspect'

export type FilterKind = PropKind | 'cohort'
export type PropertyFilter = { key: string; type: FilterKind; operator?: string; value?: unknown }
export type PropType = 'String' | 'Numeric' | 'Boolean' | 'DateTime'
export type KeyInfo = { key: string; type: PropType; share?: number; example?: string; label?: string; count?: number }

type TableRow = Record<string, unknown>
type Table = Omit<Lookup<{ rows: TableRow[] }>, 'data'> & { data: TableRow[] | undefined }

const rowsOf = (f?: DataFrame): TableRow[] =>
    f
        ? Array.from({ length: f.fields[0]?.values.length ?? 0 }, (_, i) =>
              Object.fromEntries(f.fields.map((x) => [x.name, x.values[i]]))
          )
        : []

export function useTable(query: string | undefined, family?: string): Table {
    const projectId = useProjectId()
    const r = useQuery<{ rows: TableRow[] }>({
        queryKey: ['property-filter', projectId, query, family],
        enabled: !!query && !!projectId,
        staleTime: 5 * 60_000,
        placeholderData: family ? keepPreviousData : undefined,
        queryFn: async ({ signal }) => {
            const r = await runQuery({
                signal,
                projectId,
                target: { refId: 'P', language: 'hogql', format: 'table', query: query! },
                time: { from: 'now-1d', to: 'now' },
                variables: {},
            })
            if (r.error) {
                throw new Error(r.error)
            }
            return { rows: rowsOf(r.frames[0]) }
        },
    })
    return { ...r, data: r.data?.rows }
}

export function useKeys(
    kind: PropKind,
    events: (string | null)[],
    q: string,
    enabled = true,
    scope?: Scope
): {
    keys: KeyInfo[]
    flags: KeyInfo[]
    isLoading: boolean
    searching: boolean
    capped: boolean
    sampleSize: number | undefined
    error: Error | null
    recomputing: boolean
} {
    const typed = useDebounced(q.trim(), 250)
    const conds = scope?.conds ?? []
    const sampleQuery = (c: string[]): string =>
        kind === 'event'
            ? PROPERTY_QUERIES.eventKeys(events, '', c)
            : PROPERTY_QUERIES.personKeys(scope ? events : [], c)
    const family = scope ? `keys:${kind}:${events.join(',')}` : undefined
    const live = useTable(enabled ? sampleQuery(conds) : undefined, family)
    const projectId = useProjectId()
    const before = useQueryClient().getQueryData<{ rows: TableRow[] }>([
        'property-filter',
        projectId,
        sampleQuery(conds.slice(0, -1)),
        family,
    ])?.rows
    const parent = enabled && scope && conds.length && !live.data ? before : undefined
    const sampled = { ...live, data: live.data ?? parent }
    const recomputing = !!scope && (live.isPlaceholderData || !!parent)
    const names = (sampled.data ?? []).map((r) => String(r.prop_key)).filter((k) => !isFlagKey(k))
    const types = useTable(names.length ? PROPERTY_QUERIES.definitions(kind, '', names) : undefined)
    const defs = useTable(enabled ? PROPERTY_QUERIES.definitions(kind) : undefined)
    const found = useTable(enabled && typed ? PROPERTY_QUERIES.definitions(kind, typed) : undefined, `search:${kind}`)
    const scoped = !!scope
    const all = useMemo(() => {
        if (scoped && !sampled.data) {
            return []
        }
        const typeOf = new Map<string, PropType>()
        for (const r of [...(types.data ?? []), ...(defs.data ?? []), ...(found.data ?? [])]) {
            typeOf.set(String(r.prop_key), asType(r.prop_type))
        }
        const out = new Map<string, KeyInfo>()
        for (const r of sampled.data ?? []) {
            const k = String(r.prop_key)
            out.set(k, {
                key: k,
                type: typeOf.get(k) ?? 'String',
                share: Number(r.total) ? Number(r.n) / Number(r.total) : undefined,
            })
        }
        for (const r of [...(found.data ?? []), ...(defs.data ?? [])]) {
            const k = String(r.prop_key)
            if (!out.has(k)) {
                out.set(k, { key: k, type: typeOf.get(k) ?? 'String' })
            }
        }
        return [...out.values()]
    }, [scoped, sampled.data, types.data, defs.data, found.data])
    const flags = useMemo(() => all.filter((k) => isFlagKey(k.key)), [all])
    const keys = useMemo(
        () => all.filter((k) => !isFlagKey(k.key) || (typed && k.key.toLowerCase().includes(typed.toLowerCase()))),
        [all, typed]
    )
    return {
        keys,
        flags,
        isLoading: enabled && ((sampled.isLoading && !parent) || defs.isLoading),
        searching: enabled && !!q.trim() && (typed !== q.trim() || found.isFetching),
        capped: (q.trim() ? found.data : defs.data)?.length === 500,
        sampleSize: sampled.data?.length ? Number(sampled.data[0]!.total) : undefined,
        error: sampled.error ?? defs.error,
        recomputing,
    }
}
export const asType = (t: unknown): PropType =>
    ['Numeric', 'Boolean', 'DateTime'].includes(String(t)) ? (String(t) as PropType) : 'String'

function useCohorts(enabled: boolean): Table & { cohorts: KeyInfo[] } {
    const r = useTable(enabled ? PROPERTY_QUERIES.cohorts() : undefined)
    return {
        ...r,
        cohorts: (r.data ?? []).map(
            (c): KeyInfo => ({
                key: String(c.cohort_id),
                label: String(c.name),
                type: 'String',
                count: Number(c.count),
                example: Number(c.is_static) ? 'static' : 'dynamic',
            })
        ),
    }
}

export type Scope = { conds: string[] }

export function useValues(
    kind: PropKind,
    key: string | undefined,
    type: PropType | undefined,
    events: (string | null)[],
    q = '',
    scope?: Scope
): {
    values: { value: string; n: number; share: number }[]
    stats: Spread | undefined
    isLoading: boolean
    isFetching: boolean
    error: Error | null
} {
    const typed = useDebounced(q.trim(), 250)
    const conds = scope?.conds ?? []
    const evs = kind === 'person' && !scope ? [] : events
    const values = useTable(
        key ? PROPERTY_QUERIES.values(kind, key, evs, typed, conds) : undefined,
        `values:${kind}:${key}:${conds.join('|')}`
    )
    const stats = useTable(key && type === 'Numeric' ? PROPERTY_QUERIES.stats(kind, key, evs, conds) : undefined)
    const s = stats.data?.[0]
    return {
        values: (values.data ?? []).map((r) => ({
            value: String(r.prop_value),
            n: Number(r.n),
            share: Number(r.total) ? Number(r.n) / Number(r.total) : 0,
        })),
        stats:
            s && Number(s.n) > 0
                ? { min: Number(s.prop_min), median: Number(s.median), max: Number(s.max), mean: Number(s.mean) }
                : undefined,
        isLoading: values.isLoading || stats.isLoading,
        isFetching: values.isFetching,
        error: values.error ?? stats.error,
    }
}

const CORE: Record<string, string> = {
    $browser: 'Browser',
    $os: 'OS',
    $pathname: 'Path',
    $current_url: 'Current URL',
    $device_type: 'Device type',
    $referring_domain: 'Referring domain',
    $referrer: 'Referrer',
    $screen_width: 'Screen width',
    $screen_height: 'Screen height',
    $country: 'Country',
    $geoip_country_name: 'Country',
    $geoip_city_name: 'City',
    $host: 'Host',
    $lib: 'Library',
    $initial_browser: 'Initial browser',
    $initial_referring_domain: 'Initial referring domain',
    $initial_current_url: 'Initial URL',
    $session_id: 'Session ID',
}
export const propLabel = (k: string): string =>
    (Object.hasOwn(CORE, k) ? CORE[k] : undefined) ??
    (isFlagKey(k) ? `Flag ${k.slice(k.indexOf('/') + 1)}` : undefined) ??
    (k.startsWith('$')
        ? k
              .slice(1)
              .replace(/_/g, ' ')
              .replace(/^\w/, (c) => c.toUpperCase())
        : k)

export const TYPE_ICON: Record<PropType, typeof IconLetter> = {
    String: IconLetter,
    Numeric: IconCalculator,
    Boolean: IconToggle,
    DateTime: IconCalendar,
}
const KIND_ICON: Record<FilterKind, typeof IconLetter> = { event: IconBolt, person: IconPerson, cohort: IconPeople }
const KIND_LABEL: Record<FilterKind, string> = {
    event: 'Event properties',
    person: 'Person properties',
    cohort: 'Cohorts',
}
const KIND_SHORT: Record<FilterKind, string> = { event: 'Event', person: 'Person', cohort: 'Cohort' }

export const pct = (x: number): string => (x >= 0.995 ? '100%' : x < 0.01 ? '<1%' : `${Math.round(x * 100)}%`)
export const num = (x: number): string => (Math.abs(x) >= 1000 ? compactNumber(x) : String(Math.round(x * 100) / 100))

type Op = { op: string; label: string; needs: 'list' | 'text' | 'number' | 'date' | 'none' | 'bool' }
const OPS: Record<PropType, Op[]> = {
    String: [
        { op: 'exact', label: 'is', needs: 'list' },
        { op: 'is_not', label: 'is not', needs: 'list' },
        { op: 'icontains', label: 'contains', needs: 'text' },
        { op: 'not_icontains', label: "doesn't contain", needs: 'text' },
        { op: 'regex', label: 'matches', needs: 'text' },
        { op: 'is_set', label: 'is set', needs: 'none' },
        { op: 'is_not_set', label: 'is not set', needs: 'none' },
    ],
    Numeric: [
        { op: 'exact', label: '=', needs: 'list' },
        { op: 'is_not', label: '≠', needs: 'list' },
        { op: 'gt', label: '>', needs: 'number' },
        { op: 'lt', label: '<', needs: 'number' },
        { op: 'is_set', label: 'is set', needs: 'none' },
        { op: 'is_not_set', label: 'is not set', needs: 'none' },
    ],
    Boolean: [
        { op: 'exact', label: 'is', needs: 'bool' },
        { op: 'is_set', label: 'is set', needs: 'none' },
        { op: 'is_not_set', label: 'is not set', needs: 'none' },
    ],
    DateTime: [
        { op: 'is_date_after', label: 'after', needs: 'date' },
        { op: 'is_date_before', label: 'before', needs: 'date' },
        { op: 'is_set', label: 'is set', needs: 'none' },
        { op: 'is_not_set', label: 'is not set', needs: 'none' },
    ],
}
const ALL_OPS: Record<string, string> = Object.fromEntries(
    [...Object.values(OPS).flat(), { op: 'in', label: 'in' }, { op: 'not_in', label: 'not in' }].map((o) => [
        o.op,
        o.label,
    ])
)

export function describeFilter(f: PropertyFilter, cohortName?: string): { label: string; op: string; value: string } {
    if (f.type === 'cohort') {
        return { label: 'Cohort', op: f.operator === 'not_in' ? 'not in' : 'in', value: cohortName ?? `#${f.value}` }
    }
    const values = Array.isArray(f.value) ? f.value.map(String) : f.value == null ? [] : [String(f.value)]
    const op = f.operator ?? 'exact'
    return {
        label: propLabel(f.key),
        op: Object.hasOwn(ALL_OPS, op) ? ALL_OPS[op]! : op,
        value:
            op === 'is_set' || op === 'is_not_set'
                ? ''
                : values.length > 2
                  ? `${values.slice(0, 2).join(', ')} +${values.length - 2}`
                  : values.join(', ') || '…',
    }
}

type Picked = { kind: FilterKind; info: KeyInfo }

export function FilterEditor({
    kinds = ['event', 'person', 'cohort'],
    events,
    initial,
    startKind,
    onApply,
    onCancel,
}: {
    kinds?: FilterKind[]
    events: (string | null)[]
    initial?: PropertyFilter
    startKind?: FilterKind
    onApply: (f: PropertyFilter) => void
    onCancel?: () => void
}): React.JSX.Element {
    const [picked, setPicked] = useState<Picked | undefined>(
        initial ? { kind: initial.type, info: { key: initial.key, type: guessType(initial) } } : undefined
    )
    const [draft, setDraft] = useState<Pick<PropertyFilter, 'operator' | 'value'> | undefined>(
        initial && initial.type !== 'cohort' ? { operator: initial.operator, value: initial.value } : undefined
    )
    const mode = initial ? 'edit' : 'add'
    return picked ? (
        <ValueStep
            key={`${picked.kind}:${picked.info.key}`}
            picked={picked}
            events={events}
            mode={mode}
            initial={
                picked.kind === 'cohort'
                    ? initial?.type === 'cohort'
                        ? initial
                        : undefined
                    : draft && { key: picked.info.key, type: picked.kind, ...draft }
            }
            onDraft={setDraft}
            onBack={() => setPicked(undefined)}
            onApply={onApply}
            onCancel={onCancel}
        />
    ) : (
        <KeyStep
            kinds={kinds}
            events={events}
            startKind={startKind ?? (initial?.type === 'cohort' ? 'cohort' : initial?.type)}
            selected={initial && initial.type !== 'cohort' ? { kind: initial.type, key: initial.key } : undefined}
            onPick={(p) => (p.kind === 'cohort' && mode === 'add' ? onApply(cohortFilter(p.info)) : setPicked(p))}
        />
    )
}
const cohortFilter = (c: KeyInfo, operator = 'in'): PropertyFilter => ({
    key: 'id',
    type: 'cohort',
    operator,
    value: Number(c.key),
})
const guessType = (f: PropertyFilter): PropType =>
    ['gt', 'lt', 'gte', 'lte'].includes(f.operator ?? '')
        ? 'Numeric'
        : f.operator?.startsWith('is_date')
          ? 'DateTime'
          : typeof (Array.isArray(f.value) ? f.value[0] : f.value) === 'boolean'
            ? 'Boolean'
            : 'String'

type Tab = FilterKind | 'all'
type Item = { kind: FilterKind; info: KeyInfo }
const ALL_ROWS = 6
const ALL_ROWS_SEARCHING = 25

export function KeyStep({
    kinds,
    events,
    onPick,
    selected,
    startKind,
}: {
    kinds: FilterKind[]
    events: (string | null)[]
    startKind?: FilterKind
    onPick: (p: Picked) => void
    selected?: { kind: FilterKind; key: string }
}): React.JSX.Element {
    const projectId = useProjectId()
    const [tab, setTab] = useState<Tab>(selected?.kind ?? startKind ?? (kinds.length > 1 ? 'all' : kinds[0]!))
    const [q, setQ] = useState('')
    const [active, setActive] = useState(0)
    const s = q.trim().toLowerCase()
    const eventKeys = useKeys('event', events, q, kinds.includes('event'))
    const personKeys = useKeys('person', events, q, kinds.includes('person'))
    const cohorts = useCohorts(kinds.includes('cohort'))
    const recentOf = (k: FilterKind): string => `dashboards-v2.recent.${projectId}.filter.${k}`
    const [recent, setRecent] = useState<Record<string, string[]>>(() =>
        Object.fromEntries(kinds.map((k) => [k, readStored<string[]>(recentOf(k), [])]))
    )
    const sources: Record<
        FilterKind,
        { keys: KeyInfo[]; loading: boolean; searching: boolean; capped: boolean; error: unknown }
    > = {
        event: { ...eventKeys, loading: eventKeys.isLoading },
        person: { ...personKeys, loading: personKeys.isLoading },
        cohort: {
            keys: cohorts.cohorts,
            loading: cohorts.isLoading,
            searching: false,
            capped: false,
            error: cohorts.error,
        },
    }
    const byKind = Object.fromEntries(
        kinds.map((kind) => {
            const src = sources[kind]
            const match = s
                ? src.keys.filter(
                      (k) => k.key.toLowerCase().includes(s) || (k.label ?? propLabel(k.key)).toLowerCase().includes(s)
                  )
                : src.keys
            const rec = (recent[kind] ?? []).flatMap((r) => match.filter((k) => k.key === r))
            const rest = match.filter((k) => !(recent[kind] ?? []).includes(k.key))
            const seen = rest.filter((k) => k.share !== undefined || kind === 'cohort')
            const other = rest.filter((k) => k.share === undefined && kind !== 'cohort')
            return [kind, { ...src, rec, seen, other, total: match.length }]
        })
    ) as Record<
        FilterKind,
        (typeof sources)[FilterKind] & { rec: KeyInfo[]; seen: KeyInfo[]; other: KeyInfo[]; total: number }
    >
    type Group = { title?: ReactNode; kind: FilterKind; items: KeyInfo[]; more?: number; section?: boolean }
    const groups: Group[] = []
    if (tab === 'all') {
        for (const kind of kinds) {
            const k = byKind[kind]
            const all = [...k.rec, ...k.seen, ...k.other]
            const n = s ? ALL_ROWS_SEARCHING : ALL_ROWS
            groups.push({ kind, section: true, items: all.slice(0, n), more: Math.max(0, all.length - n) })
        }
    } else {
        const k = byKind[tab]
        groups.push({ kind: tab, title: 'Recent', items: k.rec })
        groups.push({
            kind: tab,
            title: tab === 'cohort' ? undefined : tab === 'person' ? 'Seen on recent users' : 'Seen on recent events',
            items: k.seen,
        })
        groups.push({ kind: tab, title: 'Other properties · not in the recent sample', items: k.other })
    }
    const list: Item[] = groups.flatMap((g) => g.items.map((info) => ({ kind: g.kind, info })))
    const current = list[Math.min(active, list.length - 1)]
    const shownId = useDebounced(current && `${current.kind}:${current.info.key}`, 150)
    const shown = list.find((x) => `${x.kind}:${x.info.key}` === shownId)
    useEffect(() => setActive(0), [tab, s])
    const listRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
    }, [active])
    const pick = ({ kind, info }: Item): void => {
        setRecent((r) => ({ ...r, [kind]: pushRecent(recentOf(kind), [info.key], 6) }))
        onPick({ kind, info })
    }
    const count = (kind: FilterKind): string | undefined => {
        const k = byKind[kind]
        return k.loading && !k.keys.length
            ? undefined
            : `${compactNumber(k.total)}${k.capped && !k.searching ? '+' : ''}`
    }
    const tabLabel = (t: Tab): React.JSX.Element => {
        const busy =
            t === 'all'
                ? kinds.some((k) => byKind[k].loading || byKind[k].searching)
                : byKind[t].loading || byKind[t].searching
        const n =
            t === 'all'
                ? kinds.every((k) => count(k) !== undefined)
                    ? compactNumber(kinds.reduce((a, k) => a + byKind[k].total, 0))
                    : undefined
                : count(t)
        return (
            <span className="flex items-center gap-1.5">
                {t === 'all' ? 'All' : KIND_SHORT[t]}
                {busy && n === undefined ? (
                    <Spinner className="size-3 opacity-60" />
                ) : (
                    <span className="tabular-nums opacity-60" data-attr={`dashboard-v2-filter-count-${t}`}>
                        {n}
                    </span>
                )}
            </span>
        )
    }
    let index = 0
    const row = ({ kind, info: k }: Item): React.JSX.Element => {
        const i = index++
        const Icon = kind === 'cohort' ? IconPeople : TYPE_ICON[k.type]
        const label = k.label ?? propLabel(k.key)
        const isSel = selected?.kind === kind && selected.key === k.key
        return (
            <button
                key={`${kind}:${k.key}`}
                type="button"
                role="option"
                aria-selected={i === active}
                data-active={i === active}
                className={cn(
                    'flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-fill-hover',
                    i === active && 'bg-muted'
                )}
                onMouseEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                onClick={() => pick({ kind, info: k })}
            >
                <Icon
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label={kind === 'cohort' ? 'cohort' : k.type}
                />
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">{label}</span>
                    {label !== k.key && kind !== 'cohort' && (
                        <span className="truncate font-mono text-[10px] text-muted-foreground">{k.key}</span>
                    )}
                </span>
                {isSel && <IconCheck className="size-3.5 shrink-0" />}
                {k.share !== undefined && <Coverage share={k.share} />}
                {k.count !== undefined && (
                    <span className="shrink-0 tabular-nums text-muted-foreground">{compactNumber(k.count)} people</span>
                )}
            </button>
        )
    }
    const status = (kind: FilterKind): React.JSX.Element | null => {
        const k = byKind[kind]
        if (k.loading && !k.keys.length) {
            return <LoadingRows />
        }
        if (k.error && !k.keys.length) {
            return (
                <div className="px-2 py-2 text-xs text-destructive-foreground">
                    {String((k.error as Error).message)}
                </div>
            )
        }
        if (k.searching) {
            return (
                <div
                    className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground"
                    data-attr="dashboard-v2-filter-searching"
                >
                    <Spinner className="size-3.5" /> Searching every {kind} property for “{q.trim()}”…
                </div>
            )
        }
        if (!k.total) {
            return (
                <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    {s
                        ? `Nothing matches “${q.trim()}”`
                        : kind === 'cohort'
                          ? 'No cohorts in this project'
                          : 'Nothing seen recently'}
                </div>
            )
        }
        return null
    }
    return (
        <div className="flex h-full min-h-0 flex-row" data-attr="dashboard-v2-filter-keys">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <div className="flex flex-col gap-2 border-b p-2">
                    <div className="relative">
                        <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                        <Input
                            autoFocus
                            className="h-8 pl-7 text-xs"
                            placeholder={
                                tab === 'cohort'
                                    ? 'Search cohorts…'
                                    : tab === 'all'
                                      ? 'Search properties and cohorts…'
                                      : 'Search properties…'
                            }
                            value={q}
                            onChange={(e) => setQ(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                                    e.preventDefault()
                                    setActive((a) =>
                                        Math.max(0, Math.min(list.length - 1, a + (e.key === 'ArrowDown' ? 1 : -1)))
                                    )
                                } else if (e.key === 'Enter' && current) {
                                    e.preventDefault()
                                    pick(current)
                                }
                            }}
                        />
                    </div>
                    {kinds.length > 1 && (
                        <Segmented
                            value={tab}
                            options={(['all', ...kinds] as Tab[]).map((t) => [t, tabLabel(t)] as const)}
                            onChange={(t) => setTab(t as Tab)}
                        />
                    )}
                </div>
                <div
                    ref={listRef}
                    role="listbox"
                    aria-label={tab === 'all' ? 'Properties and cohorts' : KIND_LABEL[tab]}
                    className="min-h-0 flex-1 overflow-auto p-1"
                >
                    {groups.map((g, gi) =>
                        g.section ? (
                            <section key={g.kind} data-attr={`dashboard-v2-filter-section-${g.kind}`}>
                                <div className="flex items-center gap-1.5 px-2 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                    {KIND_LABEL[g.kind]}
                                    {count(g.kind) !== undefined ? (
                                        <span className="tabular-nums font-normal normal-case">{count(g.kind)}</span>
                                    ) : (
                                        <Spinner className="size-3" />
                                    )}
                                </div>
                                {g.items.map((info) => row({ kind: g.kind, info }))}
                                {!g.items.length && status(g.kind)}
                                {g.items.length > 0 && byKind[g.kind].searching && status(g.kind)}
                                {!!g.more && (
                                    <button
                                        type="button"
                                        className="w-full cursor-pointer rounded px-2 py-1 text-left text-xs font-medium text-foreground hover:bg-fill-hover"
                                        onClick={() => setTab(g.kind)}
                                    >
                                        Show all {compactNumber(g.items.length + g.more)}{' '}
                                        {KIND_LABEL[g.kind].toLowerCase()} →
                                    </button>
                                )}
                            </section>
                        ) : (
                            g.items.length > 0 && (
                                <div key={gi}>
                                    {g.title && groups.filter((x) => x.items.length).length > 1 && (
                                        <Heading>{g.title}</Heading>
                                    )}
                                    {g.items.map((info) => row({ kind: g.kind, info }))}
                                </div>
                            )
                        )
                    )}
                    {tab !== 'all' && (!list.length || byKind[tab].searching) && status(tab)}
                </div>
            </div>
            <div className="w-80 shrink-0 overflow-auto border-l">
                {shown ? (
                    <Details kind={shown.kind} info={shown.info} events={events} />
                ) : (
                    <div className="p-3 text-xs text-muted-foreground">Point at a property to see its values</div>
                )}
            </div>
        </div>
    )
}

export const Heading = ({ children }: { children: ReactNode }): React.JSX.Element => (
    <div className="px-2 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {children}
    </div>
)
export const LoadingRows = (): React.JSX.Element => (
    <div className="flex flex-col gap-1.5 p-2" aria-label="Loading">
        {[70, 50, 85, 60].map((w) => (
            <div key={w} className="h-3 animate-pulse rounded bg-muted" style={{ width: `${w}%` }} />
        ))}
    </div>
)
export const Coverage = ({ share }: { share: number }): React.JSX.Element => (
    <span
        className="flex shrink-0 items-center gap-1.5 tabular-nums text-muted-foreground"
        title={`Set on ${pct(share)} of recent events`}
    >
        <span className="h-1 w-8 overflow-hidden rounded-full bg-muted">
            <span
                className="block h-full rounded-full bg-primary"
                style={{ width: `${Math.max(4, share * 100)}%`, opacity: 0.6 }}
            />
        </span>
        {pct(share)}
    </span>
)

function Details({
    kind,
    info,
    events,
}: {
    kind: FilterKind
    info: KeyInfo
    events: (string | null)[]
}): React.JSX.Element {
    const isProp = kind !== 'cohort'
    const v = useValues(isProp ? (kind as PropKind) : 'event', isProp ? info.key : undefined, info.type, events)
    const Icon = isProp ? TYPE_ICON[info.type] : IconPeople
    return (
        <div className="flex flex-col gap-2 p-3 text-xs" data-attr="dashboard-v2-filter-details">
            <div className="flex flex-col gap-0.5">
                <span className="font-semibold">{info.label ?? propLabel(info.key)}</span>
                {isProp && propLabel(info.key) !== info.key && (
                    <span className="break-all font-mono text-[10px] text-muted-foreground">{info.key}</span>
                )}
                <span className="mt-1 flex items-center gap-1 text-muted-foreground">
                    <Icon className="size-3" />
                    {isProp
                        ? `${info.type === 'Numeric' ? 'Number' : info.type === 'DateTime' ? 'Date' : info.type === 'Boolean' ? 'True / false' : 'Text'} · ${KIND_SHORT[kind].toLowerCase()} property`
                        : `${info.example} cohort`}
                </span>
            </div>
            {info.share !== undefined && (
                <div className="text-muted-foreground">Set on {pct(info.share)} of recent events</div>
            )}
            {!isProp && info.count !== undefined && (
                <div className="text-muted-foreground">{info.count.toLocaleString()} people</div>
            )}
            {v.stats && <Stats stats={v.stats} />}
            {isProp && (
                <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Top values
                    </span>
                    {v.isLoading && <LoadingRows />}
                    {!v.isLoading && !v.values.length && (
                        <span className="text-muted-foreground">No values recently</span>
                    )}
                    {v.values.slice(0, 8).map((x) => (
                        <ValueBar key={x.value} value={x.value} share={x.share} n={x.n} />
                    ))}
                </div>
            )}
        </div>
    )
}
type Spread = { min: number; median: number; max: number; mean: number }
export const Stats = ({ stats }: { stats: Spread }): React.JSX.Element => (
    <div className="grid grid-cols-4 gap-1 rounded-md bg-muted p-1.5 text-center" data-attr="dashboard-v2-filter-stats">
        {(['min', 'median', 'max', 'mean'] as const).map((k) => (
            <div key={k} className="flex flex-col">
                <span className="text-[10px] text-muted-foreground">{k === 'mean' ? 'avg' : k}</span>
                <span className="font-medium tabular-nums">{num(stats[k])}</span>
            </div>
        ))}
    </div>
)
const QuickNumbers = ({ stats, onPick }: { stats: Spread; onPick: (x: number) => void }): React.JSX.Element => (
    <div className="flex flex-wrap gap-1">
        {(['min', 'median', 'mean', 'max'] as const).map((k) => (
            <button
                key={k}
                type="button"
                className="cursor-pointer rounded-full border px-2 py-0.5 text-muted-foreground hover:text-foreground"
                onClick={() => onPick(Math.round(stats[k] * 100) / 100)}
            >
                {k === 'mean' ? 'avg' : k} {num(stats[k])}
            </button>
        ))}
    </div>
)
export const ValueBar = ({ value, share, n }: { value: string; share: number; n: number }): React.JSX.Element => (
    <div
        className="relative flex items-center gap-2 overflow-hidden rounded px-1.5 py-0.5"
        title={`${n.toLocaleString()} (${pct(share)})`}
    >
        <span
            className="absolute inset-y-0 left-0 rounded bg-primary"
            style={{ width: `${Math.max(2, share * 100)}%`, opacity: 0.12 }}
        />
        <span className="relative min-w-0 flex-1 truncate">{value}</span>
        <span className="relative shrink-0 tabular-nums text-muted-foreground">{pct(share)}</span>
    </div>
)

function ValueStep({
    picked,
    events,
    initial,
    mode,
    onDraft,
    onBack,
    onApply,
    onCancel,
}: {
    picked: Picked
    events: (string | null)[]
    initial?: PropertyFilter
    mode: 'add' | 'edit'
    onDraft?: (d: Pick<PropertyFilter, 'operator' | 'value'>) => void
    onBack?: () => void
    onApply: (f: PropertyFilter) => void
    onCancel?: () => void
}): React.JSX.Element {
    const { kind, info } = picked
    const cohorts = useCohorts(kind === 'cohort')
    if (kind === 'cohort') {
        const id = info.key === 'id' ? String(initial?.value ?? '') : info.key
        const c = cohorts.cohorts.find((x) => x.key === id)
        return (
            <CohortStep
                name={c?.label ?? `Cohort #${id}`}
                count={c?.count}
                operator={initial?.operator ?? 'in'}
                mode={mode}
                onBack={onBack}
                onApply={(operator) => onApply(cohortFilter({ ...info, key: id }, operator))}
                onCancel={onCancel}
            />
        )
    }
    return (
        <PropertyValueStep
            mode={mode}
            onDraft={onDraft}
            kind={kind}
            info={info}
            events={events}
            initial={initial}
            onBack={onBack}
            onApply={onApply}
            onCancel={onCancel}
        />
    )
}

function PropertyValueStep({
    kind,
    info,
    events,
    initial,
    mode,
    onDraft,
    onBack,
    onApply,
    onCancel,
}: {
    mode: 'add' | 'edit'
    onDraft?: (d: Pick<PropertyFilter, 'operator' | 'value'>) => void
    kind: PropKind
    info: KeyInfo
    events: (string | null)[]
    initial?: PropertyFilter
    onBack?: () => void
    onApply: (f: PropertyFilter) => void
    onCancel?: () => void
}): React.JSX.Element {
    const projectId = useProjectId()
    const [introspect, setIntrospect] = useState(false)
    const oneEvent = events.length === 1 && events[0] && !events[0].startsWith('action:') ? events[0] : undefined
    const picked = (n: Nav): string | undefined => n.conds.find((c) => c.kind === kind && c.key === info.key)?.value
    const ops = OPS[info.type]
    const [op, setOp] = useState(
        initial?.operator && ops.some((o) => o.op === initial.operator) ? initial.operator : ops[0]!.op
    )
    const need = ops.find((o) => o.op === op)!.needs
    const init = Array.isArray(initial?.value)
        ? initial.value.map(String)
        : initial?.value != null && typeof initial.value !== 'boolean'
          ? [String(initial.value)]
          : []
    const [chosen, setChosen] = useState<string[]>(init)
    const [text, setText] = useState(init[0] ?? '')
    const [bool, setBool] = useState<boolean | undefined>(
        typeof initial?.value === 'boolean'
            ? initial.value
            : Array.isArray(initial?.value) && typeof initial.value[0] === 'boolean'
              ? initial.value[0]
              : undefined
    )
    const [q, setQ] = useState('')
    const v = useValues(kind, info.key, info.type, events, need === 'list' ? q : '')
    const Icon = TYPE_ICON[info.type]
    const value: unknown =
        need === 'list'
            ? info.type === 'Numeric'
                ? chosen.map(Number)
                : chosen
            : need === 'number'
              ? text.trim() === ''
                  ? undefined
                  : Number(text)
              : need === 'bool'
                ? bool === undefined
                    ? undefined
                    : [bool]
                : need === 'none'
                  ? op
                  : text.trim() || undefined
    const valid =
        need === 'list' ? chosen.length > 0 : need === 'number' ? Number.isFinite(value as number) : value !== undefined
    const apply = (): false | void => valid && onApply({ key: info.key, type: kind, operator: op, value })
    useEffect(() => onDraft?.({ operator: op, value }), [op, JSON.stringify(value)])
    const fresh =
        q.trim() && !v.values.some((x) => x.value === q.trim()) && !chosen.includes(q.trim()) ? q.trim() : undefined
    const toggle = (x: string): void => setChosen((c) => (c.includes(x) ? c.filter((y) => y !== x) : [...c, x]))
    return (
        <div
            className="flex h-full min-h-0 flex-col"
            data-attr="dashboard-v2-filter-value"
            onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || need !== 'list')) {
                    e.preventDefault()
                    apply()
                }
            }}
        >
            <div className="flex items-center gap-2 border-b p-2">
                {onBack && (
                    <Button
                        variant="outline"
                        size="xs"
                        className="shrink-0"
                        onClick={onBack}
                        data-attr="dashboard-v2-filter-back"
                    >
                        <IconArrowLeft className="size-3.5" /> {mode === 'edit' ? 'Change property' : 'Properties'}
                    </Button>
                )}
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-xs font-semibold">{propLabel(info.key)}</span>
                    <span className="truncate font-mono text-[10px] text-muted-foreground">
                        {KIND_SHORT[kind].toLowerCase()} · {info.key}
                    </span>
                </span>
                {info.share !== undefined && <Coverage share={info.share} />}
                <Button
                    variant="outline"
                    size="xs"
                    className="shrink-0"
                    title="Its values in Introspect, where you can narrow by other properties first"
                    data-attr="dashboard-v2-filter-introspect"
                    onClick={() => setIntrospect(true)}
                >
                    <IconTelescope className="size-3.5" /> Introspect
                </Button>
            </div>
            {introspect && (
                <IntrospectDialog
                    projectId={projectId}
                    start={{
                        source: kind === 'person' && !oneEvent ? 'persons' : 'events',
                        entity: oneEvent,
                        conds: [],
                        attr: { kind, key: info.key, type: info.type },
                    }}
                    pick={{
                        action: mode === 'edit' ? 'Update filter' : 'Add filter',
                        describe: (n) => {
                            const v = picked(n)
                            return v === undefined ? undefined : `${propLabel(info.key)} = ${v}`
                        },
                        hint: `Click a value of ${propLabel(info.key)} to filter to it`,
                        apply: (n) =>
                            onApply({
                                key: info.key,
                                type: kind,
                                operator: 'exact',
                                value: [
                                    info.type === 'Numeric'
                                        ? Number(picked(n))
                                        : info.type === 'Boolean'
                                          ? picked(n) === 'true'
                                          : picked(n)!,
                                ],
                            }),
                    }}
                    onClose={() => setIntrospect(false)}
                />
            )}
            <div className="flex min-h-0 flex-1">
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex flex-wrap gap-1 border-b p-2" role="radiogroup" aria-label="Condition">
                        {ops.map((o) => (
                            <button
                                key={o.op}
                                type="button"
                                role="radio"
                                aria-checked={o.op === op}
                                className={cn(
                                    'cursor-pointer rounded-full border px-2.5 py-1 text-xs hover:border-foreground',
                                    o.op === op
                                        ? 'border-foreground bg-fill-selected font-medium text-foreground'
                                        : 'text-muted-foreground hover:text-foreground'
                                )}
                                onClick={() => setOp(o.op)}
                            >
                                {o.label}
                            </button>
                        ))}
                    </div>
                    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2 text-xs">
                        {v.stats && (need === 'number' || need === 'list') && <Stats stats={v.stats} />}
                        {need === 'list' && (
                            <>
                                <div className="relative">
                                    {v.isFetching ? (
                                        <Spinner className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2" />
                                    ) : (
                                        <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                                    )}
                                    <Input
                                        autoFocus
                                        className="h-8 pl-7 text-xs"
                                        placeholder={
                                            info.type === 'Numeric'
                                                ? 'Search or type a number…'
                                                : 'Search or type a value…'
                                        }
                                        value={q}
                                        onChange={(e) => setQ(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) {
                                                e.preventDefault()
                                                const only = v.values.length === 1 ? v.values[0]!.value : undefined
                                                const x = fresh ?? only
                                                if (x) {
                                                    toggle(x)
                                                    setQ('')
                                                }
                                            }
                                        }}
                                    />
                                </div>
                                {chosen.length > 0 && (
                                    <div className="flex flex-wrap gap-1">
                                        {chosen.map((c) => (
                                            <span
                                                key={c}
                                                className="flex items-center gap-1 rounded-md bg-fill-selected py-0.5 pl-2 pr-1"
                                            >
                                                <span className="max-w-48 truncate">{c}</span>
                                                <button
                                                    type="button"
                                                    aria-label={`Remove ${c}`}
                                                    onClick={() => toggle(c)}
                                                >
                                                    <IconX className="size-3" />
                                                </button>
                                            </span>
                                        ))}
                                    </div>
                                )}
                                <div className="flex flex-col" role="listbox" aria-multiselectable aria-label="Values">
                                    {fresh && (
                                        <button
                                            type="button"
                                            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-fill-hover"
                                            onClick={() => {
                                                toggle(fresh)
                                                setQ('')
                                            }}
                                        >
                                            <IconPlus className="size-3.5" /> Use “{fresh}”
                                        </button>
                                    )}
                                    {v.isLoading && <LoadingRows />}
                                    {!v.isLoading && !v.values.length && !fresh && (
                                        <span className="px-2 py-1 text-muted-foreground">
                                            No values seen recently: type one
                                        </span>
                                    )}
                                    {v.values.map((x) => {
                                        const on = chosen.includes(x.value)
                                        return (
                                            <button
                                                key={x.value}
                                                type="button"
                                                role="option"
                                                aria-selected={on}
                                                className="relative flex cursor-pointer items-center gap-2 overflow-hidden rounded px-2 py-1 text-left hover:bg-fill-hover"
                                                onClick={() => toggle(x.value)}
                                            >
                                                <span
                                                    className="absolute inset-y-0.5 left-0 rounded bg-primary"
                                                    style={{ width: `${Math.max(1, x.share * 100)}%`, opacity: 0.12 }}
                                                />
                                                <Checkbox
                                                    checked={on}
                                                    className="pointer-events-none relative"
                                                    tabIndex={-1}
                                                />
                                                <span className="relative min-w-0 flex-1 truncate">{x.value}</span>
                                                <span className="relative shrink-0 tabular-nums text-muted-foreground">
                                                    {compactNumber(x.n)} · {pct(x.share)}
                                                </span>
                                            </button>
                                        )
                                    })}
                                </div>
                            </>
                        )}
                        {(need === 'text' || need === 'number') && (
                            <Input
                                autoFocus
                                type={need === 'number' ? 'number' : 'text'}
                                inputMode={need === 'number' ? 'decimal' : undefined}
                                className="h-8 text-xs"
                                placeholder={
                                    op === 'regex'
                                        ? 'A regular expression, e.g. ^/docs/'
                                        : need === 'number'
                                          ? 'A number'
                                          : 'Text'
                                }
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                            />
                        )}
                        {need === 'number' && v.stats && (
                            <QuickNumbers stats={v.stats} onPick={(x) => setText(String(x))} />
                        )}
                        {need === 'bool' && (
                            <div className="grid grid-cols-2 gap-2">
                                {[true, false].map((b) => {
                                    const n = v.values.find((x) => x.value === String(b))
                                    return (
                                        <button
                                            key={String(b)}
                                            type="button"
                                            aria-pressed={bool === b}
                                            className={cn(
                                                'flex cursor-pointer flex-col items-center gap-0.5 rounded-md border p-2 hover:border-foreground',
                                                bool === b && 'border-foreground bg-fill-selected'
                                            )}
                                            onClick={() => setBool(b)}
                                        >
                                            <span className="font-medium">{String(b)}</span>
                                            {n && (
                                                <span className="text-muted-foreground">{pct(n.share)} of events</span>
                                            )}
                                        </button>
                                    )
                                })}
                            </div>
                        )}
                        {need === 'date' && (
                            <Input
                                type="date"
                                className="h-8 text-xs"
                                value={text.slice(0, 10)}
                                onChange={(e) => setText(e.target.value)}
                            />
                        )}
                        {need === 'none' && (
                            <span className="text-muted-foreground">
                                {op === 'is_set' ? 'Events where it has any value' : 'Events without it'}
                                {info.share !== undefined &&
                                    ` (${pct(op === 'is_set' ? info.share : 1 - info.share)} recently)`}
                            </span>
                        )}
                    </div>
                </div>
                <div className="w-80 shrink-0 overflow-auto border-l">
                    <Details kind={kind} info={info} events={events} />
                </div>
            </div>
            <Footer
                summary={
                    valid
                        ? Object.values(describeFilter({ key: info.key, type: kind, operator: op, value }))
                              .filter(Boolean)
                              .join(' ')
                        : need === 'list'
                          ? 'Pick one or more values'
                          : 'Enter a value'
                }
                valid={valid}
                label={mode === 'edit' ? 'Update filter' : 'Add filter'}
                onApply={apply}
                onCancel={onCancel}
            />
        </div>
    )
}

function CohortStep({
    name,
    count,
    operator,
    mode,
    onBack,
    onApply,
    onCancel,
}: {
    name: string
    count?: number
    operator: string
    mode: 'add' | 'edit'
    onBack?: () => void
    onApply: (operator: string) => void
    onCancel?: () => void
}): React.JSX.Element {
    const [op, setOp] = useState(operator)
    return (
        <div className="flex h-full min-h-0 flex-col text-xs" data-attr="dashboard-v2-filter-value">
            <div className="flex items-center gap-2 border-b p-2">
                {onBack && (
                    <Button
                        variant="outline"
                        size="xs"
                        className="shrink-0"
                        onClick={onBack}
                        data-attr="dashboard-v2-filter-back"
                    >
                        <IconArrowLeft className="size-3.5" /> {mode === 'edit' ? 'Change cohort' : 'Cohorts'}
                    </Button>
                )}
                <IconPeople className="size-3.5 text-muted-foreground" />
                <span className="font-semibold">{name}</span>
                {count !== undefined && <span className="text-muted-foreground">{count.toLocaleString()} people</span>}
            </div>
            <div className="flex-1 p-3">
                <Segmented
                    value={op}
                    options={[
                        ['in', 'In the cohort'],
                        ['not_in', 'Not in it'],
                    ]}
                    onChange={setOp}
                />
            </div>
            <Footer
                summary={`${op === 'in' ? 'In' : 'Not in'} ${name}`}
                valid
                label={mode === 'edit' ? 'Update filter' : 'Add filter'}
                onApply={() => onApply(op)}
                onCancel={onCancel}
            />
        </div>
    )
}

function Footer({
    summary,
    valid,
    label,
    onApply,
    onCancel,
}: {
    summary: ReactNode
    valid: boolean
    label: string
    onApply: () => void
    onCancel?: () => void
}): React.JSX.Element {
    return (
        <div className="flex items-center gap-3 border-t bg-muted px-3 py-2.5">
            <span
                className={cn('min-w-0 flex-1 truncate text-xs', valid ? 'font-medium' : 'text-muted-foreground')}
                data-attr="dashboard-v2-filter-summary"
            >
                {summary}
            </span>
            <div className="flex gap-2">
                {onCancel && (
                    <Button variant="outline" onClick={onCancel}>
                        Cancel
                    </Button>
                )}
                <Button variant="primary" disabled={!valid} onClick={onApply} data-attr="dashboard-v2-filter-apply">
                    {label}
                </Button>
            </div>
        </div>
    )
}

export function FilterDialog({
    title,
    context,
    others = [],
    children,
    onClose,
}: {
    title: string
    context?: ReactNode
    others?: PropertyFilter[]
    children: ReactNode
    onClose: () => void
}): React.JSX.Element {
    const cohorts = useCohorts(others.some((f) => f.type === 'cohort'))
    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent
                size="wide"
                className="flex h-[min(38rem,85dvh)] flex-col gap-0"
                data-attr="dashboard-v2-filter-dialog"
            >
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    {context && <DialogDescription>{context}</DialogDescription>}
                    {others.length > 0 && (
                        <div
                            className="flex flex-wrap items-center gap-1 pt-1 text-xs"
                            data-attr="dashboard-v2-filter-context"
                        >
                            <span className="text-muted-foreground">Already filtering on</span>
                            {others.map((f, i) => {
                                const d = describeFilter(
                                    f,
                                    cohorts.cohorts.find((c) => c.key === String(f.value))?.label
                                )
                                return (
                                    <span
                                        key={i}
                                        className="flex items-center gap-1 rounded-md border bg-muted px-1.5 py-0.5"
                                    >
                                        <span className="font-medium">{d.label}</span>
                                        <span className="text-muted-foreground">{d.op}</span>
                                        {d.value && <span className="max-w-40 truncate">{d.value}</span>}
                                    </span>
                                )
                            })}
                        </div>
                    )}
                </DialogHeader>
                <div className="min-h-0 flex-1 px-4 pb-4">
                    <div className="h-full overflow-hidden rounded-md border bg-card">{children}</div>
                </div>
            </DialogContent>
        </Dialog>
    )
}

export function PropertyFilters({
    events,
    value,
    onChange,
    kinds,
    context,
    autoAdd,
    onDismiss,
}: {
    events: (string | null)[]
    value: PropertyFilter[]
    onChange: (f: PropertyFilter[]) => void
    kinds?: FilterKind[]
    context?: ReactNode
    autoAdd?: boolean
    onDismiss?: () => void
}): React.JSX.Element {
    const [editing, setEditing] = useState<number | 'new' | undefined>(autoAdd ? 'new' : undefined)
    const cohorts = useCohorts(value.some((f) => f.type === 'cohort'))
    const close = (): void => {
        if (editing === 'new') {
            onDismiss?.()
        }
        setEditing(undefined)
    }
    const current = typeof editing === 'number' ? value[editing] : undefined
    return (
        <div className="flex flex-wrap items-center gap-1.5" data-attr="dashboard-v2-property-filters">
            {value.map((f, i) => (
                <FilterChip
                    key={i}
                    f={f}
                    cohortName={cohorts.cohorts.find((c) => c.key === String(f.value))?.label}
                    onOpen={() => setEditing(i)}
                    onRemove={() => onChange(value.filter((_, j) => j !== i))}
                />
            ))}
            <Button
                variant="outline"
                size="xs"
                className="text-muted-foreground"
                data-attr="dashboard-v2-add-filter"
                onClick={() => setEditing('new')}
            >
                <IconPlus className="size-3" /> Filter
            </Button>
            {editing !== undefined && (
                <FilterDialog
                    title={current ? 'Change filter' : 'Add a filter'}
                    context={context}
                    others={value.filter((_, j) => j !== editing)}
                    onClose={close}
                >
                    <FilterEditor
                        kinds={kinds}
                        events={events}
                        initial={current}
                        onApply={(f) => {
                            onChange(current ? value.map((x, j) => (j === editing ? f : x)) : [...value, f])
                            setEditing(undefined)
                        }}
                        onCancel={close}
                    />
                </FilterDialog>
            )}
        </div>
    )
}

function FilterChip({
    f,
    cohortName,
    onOpen,
    onRemove,
}: {
    f: PropertyFilter
    cohortName?: string
    onOpen: () => void
    onRemove: () => void
}): React.JSX.Element {
    const d = describeFilter(f, cohortName)
    const known = Object.hasOwn(KIND_ICON, f.type)
    const Icon = known ? KIND_ICON[f.type] : IconBolt
    const body = (
        <>
            <Icon className="size-3 shrink-0 text-muted-foreground" />
            <span className="max-w-32 truncate font-medium">{d.label}</span>
            <span className="shrink-0 text-muted-foreground">{d.op}</span>
            {d.value && <span className="max-w-40 truncate">{d.value}</span>}
        </>
    )
    return (
        <span
            className="flex max-w-full items-center rounded-md border bg-muted text-xs"
            data-attr="dashboard-v2-filter-chip"
        >
            {known ? (
                <button
                    type="button"
                    className="flex min-w-0 cursor-pointer items-center gap-1 rounded-l-md py-1 pl-2 pr-1 hover:bg-fill-hover"
                    title={`${KIND_SHORT[f.type]}: ${f.key}`}
                    onClick={onOpen}
                >
                    {body}
                </button>
            ) : (
                <span className="flex min-w-0 items-center gap-1 py-1 pl-2 pr-1" title={`${f.type}: ${f.key}`}>
                    {body}
                </span>
            )}
            <button
                type="button"
                className="px-1 py-1 text-muted-foreground hover:text-foreground"
                aria-label="Remove filter"
                onClick={onRemove}
            >
                <IconX className="size-3" />
            </button>
        </span>
    )
}

export function BreakdownPicker({
    events,
    value,
    onChange,
    context,
}: {
    events: (string | null)[]
    value?: { key: string; kind: PropKind }
    onChange: (v?: { key: string; kind: PropKind }) => void
    context?: ReactNode
}): React.JSX.Element {
    const [open, setOpen] = useState(false)
    const Icon = value ? KIND_ICON[value.kind] : IconStack
    return (
        <div className="flex items-center gap-1" data-attr="dashboard-v2-breakdown-picker">
            <Button
                variant="outline"
                size="sm"
                className="h-7 max-w-72 justify-start gap-1.5 font-normal"
                onClick={() => setOpen(true)}
            >
                <Icon className="size-3.5 shrink-0 opacity-70" />
                <span className="truncate">{value ? propLabel(value.key) : '+ Break down by a property'}</span>
            </Button>
            {value && (
                <Button
                    variant="default"
                    size="icon-xs"
                    aria-label="Remove breakdown"
                    onClick={() => onChange(undefined)}
                >
                    <IconX className="size-3.5" />
                </Button>
            )}
            {open && (
                <FilterDialog
                    title="Break down by"
                    context={context ?? 'A series per value of the property'}
                    onClose={() => setOpen(false)}
                >
                    <KeyStep
                        kinds={['event', 'person']}
                        events={events}
                        selected={value}
                        onPick={(p) => {
                            onChange({ key: p.info.key, kind: p.kind as PropKind })
                            setOpen(false)
                        }}
                    />
                </FilterDialog>
            )}
        </div>
    )
}

export function useActionOptions(): {
    actions: { pick: string; name: string; description: string | undefined }[]
    isLoading: boolean
} {
    const r = useTable(PROPERTY_QUERIES.actions())
    const actions = (r.data ?? []).map((a) => ({
        pick: actionPick(Number(a.action_id), String(a.name)),
        name: String(a.name),
        description: a.description ? String(a.description) : undefined,
    }))
    return { actions, isLoading: r.isLoading }
}

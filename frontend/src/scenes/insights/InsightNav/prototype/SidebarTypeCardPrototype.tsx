import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCorrelationAnalysis, IconGlobe, IconGraph } from '@posthog/icons'

import {
    FEATURE_FLAGS,
    FunnelLayout,
    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
    RETENTION_RECURRING,
} from 'lib/constants'
import { Icon123 } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import {
    FunnelSketch,
    GenericInsightSketch,
    PathsSketch,
    RetentionSketch,
    TrendsSketch,
} from 'scenes/saved-insights/InsightTypeSketch'
import {
    INSIGHT_TYPES_METADATA,
    InsightTypeMetadata,
    QUERY_TYPES_METADATA,
} from 'scenes/saved-insights/insightTypesMetadata'

import { EditorFilterGroup } from '~/queries/nodes/InsightViz/EditorFilterGroup'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    EditorFilterProps,
    FunnelVizType,
    InsightEditorFilterGroup,
    InsightType,
    PathType,
} from '~/types'

/**
 * THROWAWAY PROTOTYPE: variants E to H of the insight type switcher, see InsightTypeSwitcherPrototype.tsx.
 *
 * All four render a card above the filters in the left editor sidebar (tinted accent card so it
 * stands out from the filter sections) and differ in how they structure the type choice:
 *   sidebar           (E): flat icon tile row for the six types + a "View as" display row
 *   sidebar-questions (F): four families grouped by the question you ask; stickiness and
 *                          lifecycle live under retention; the sub row picks the method
 *   sidebar-families  (G): four families grouped by shared setup; stickiness and lifecycle
 *                          live under trends (same series editor, lossless switch); retention
 *                          splits into recurring vs first time; paths picks its event scope
 *   sidebar-modes     (H): no regrouping; the six types in a select plus a uniform "Mode" row
 *                          surfacing each type's buried subtype picker
 *   sidebar-sketches  (I): visual alternative; plain surface card where the hand-drawn chart
 *                          sketches carry the weight (same grouping as G)
 *   sidebar-list      (J): visual alternative; no card chrome, families as quiet rows with
 *                          methods indented under the active one (same grouping as G)
 *   sidebar-compact   (K): visual alternative; family and method as two bare selects on one
 *                          row, no decoration at all (same grouping as G)
 *   sidebar-section   (L): a native "Visualization" section styled exactly like General and
 *                          Filters, with the display menu's groups promoted to the top level
 *                          (time series, total value, world map, calendar heatmap, funnel,
 *                          retention, ...) and the display options as suboptions
 *
 * Type switches go through setActiveView (config carry-over intact); mode switches go through
 * updateInsightFilter on the live query. Rendered from EditorFilters, inert (null) unless the
 * URL has a matching ?variant=.
 */

export interface ExtraTypeEntry {
    key: string
    name: string
    description: string
    icon: React.ComponentType<any>
    tag: string
    disabledReason: string
}

export const CORE_TYPES: InsightType[] = [
    InsightType.TRENDS,
    InsightType.FUNNELS,
    InsightType.RETENTION,
    InsightType.PATHS,
    InsightType.STICKINESS,
    InsightType.LIFECYCLE,
]

export const EXTRA_TYPES: ExtraTypeEntry[] = [
    {
        key: 'CALENDAR_HEATMAP',
        name: 'Calendar heatmap',
        description: QUERY_TYPES_METADATA[NodeKind.CalendarHeatmapQuery].description ?? '',
        icon: QUERY_TYPES_METADATA[NodeKind.CalendarHeatmapQuery].icon,
        tag: 'Beta',
        disabledReason: 'Real query type without a tab slot today. Display-only in this prototype',
    },
    {
        key: 'SQL',
        name: 'SQL',
        description: INSIGHT_TYPES_METADATA[InsightType.SQL].description ?? '',
        icon: INSIGHT_TYPES_METADATA[InsightType.SQL].icon,
        tag: 'Editor',
        disabledReason: 'Would open the SQL editor. Display-only in this prototype',
    },
    {
        key: 'EXAMPLE_SANKEY',
        name: 'Sankey flow',
        description: 'Example future type, here to show how the list scales.',
        icon: IconGraph,
        tag: 'Example',
        disabledReason: 'Example future type. Display-only in this prototype',
    },
    {
        key: 'EXAMPLE_ANOMALY',
        name: 'Anomaly detection',
        description: 'Example future type, here to show how the list scales.',
        icon: IconCorrelationAnalysis,
        tag: 'Example',
        disabledReason: 'Example future type. Display-only in this prototype',
    },
]

interface SubtypeOption {
    value: string
    label: string
}

const TRENDS_VIEWS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar' },
    { value: ChartDisplayType.BoldNumber, label: 'Number' },
    { value: ChartDisplayType.ActionsTable, label: 'Table' },
    { value: ChartDisplayType.ActionsPie, label: 'Pie' },
]

const STICKINESS_VIEWS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar' },
]

const FUNNEL_VIEWS: SubtypeOption[] = [
    { value: FunnelVizType.Steps, label: 'Steps' },
    { value: FunnelVizType.TimeToConvert, label: 'Time to convert' },
    { value: FunnelVizType.Trends, label: 'Trends' },
]

const PATH_SCOPES: { key: string; label: string; value: PathType[] }[] = [
    { key: 'pages', label: 'Pages', value: [PathType.PageView] },
    { key: 'screens', label: 'Screens', value: [PathType.Screen] },
    { key: 'custom-events', label: 'Custom events', value: [PathType.CustomEvent] },
    { key: 'all', label: 'All events', value: [PathType.PageView, PathType.Screen, PathType.CustomEvent] },
]

// --- Shared building blocks ---

function CardShell({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="border-accent bg-accent-highlight-secondary mb-3 rounded-lg border p-3"
            data-attr="prototype-insight-type-sidebar-card"
        >
            {children}
        </div>
    )
}

function CardLabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-accent text-[0.625rem] font-semibold tracking-wide uppercase">{children}</div>
}

interface SubOption {
    key: string
    label: string
    active?: boolean
    onSelect?: () => void
    disabledReason?: string
}

function SubChips({ options, dataAttrPrefix }: { options: SubOption[]; dataAttrPrefix: string }): JSX.Element {
    return (
        <div className="mt-1 flex flex-wrap gap-1">
            {options.map((option) => {
                const chip = (
                    <button
                        key={option.key}
                        type="button"
                        aria-pressed={option.active}
                        onClick={option.disabledReason ? undefined : option.onSelect}
                        className={clsx(
                            'rounded-md border px-2 py-1 text-xs font-medium transition-colors',
                            option.active
                                ? 'border-accent bg-surface-primary text-accent shadow-sm'
                                : 'text-secondary border-transparent',
                            option.disabledReason ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
                            !option.disabledReason && !option.active && 'hover:bg-surface-primary hover:text-primary'
                        )}
                        data-attr={`${dataAttrPrefix}-${option.key.toLowerCase()}`}
                    >
                        {option.label}
                    </button>
                )
                return option.disabledReason ? (
                    <Tooltip key={option.key} title={option.disabledReason} placement="top">
                        {chip}
                    </Tooltip>
                ) : (
                    chip
                )
            })}
        </div>
    )
}

type ApplyInsightFilter = (insightFilter: Record<string, unknown>) => void

function funnelVizSubs(current: FunnelVizType | undefined, apply: ApplyInsightFilter): SubOption[] {
    const active = current ?? FunnelVizType.Steps
    return FUNNEL_VIEWS.map((view) => ({
        key: view.value,
        label: view.label,
        active: active === view.value,
        onSelect: () => apply({ funnelVizType: view.value }),
    }))
}

function retentionTypeSubs(current: string | undefined, apply: ApplyInsightFilter): SubOption[] {
    const active = current ?? RETENTION_RECURRING
    return [
        {
            key: 'recurring',
            label: 'Recurring',
            active: active === RETENTION_RECURRING,
            onSelect: () => apply({ retentionType: RETENTION_RECURRING }),
        },
        {
            key: 'first-time',
            label: 'First time',
            active: active === RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
            onSelect: () => apply({ retentionType: RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS }),
        },
    ]
}

function pathScopeSubs(current: PathType[] | undefined, apply: ApplyInsightFilter): SubOption[] {
    const activeKey = [...(current ?? [PathType.PageView])].sort().join(',')
    return PATH_SCOPES.map((scope) => ({
        key: scope.key,
        label: scope.label,
        active: activeKey === [...scope.value].sort().join(','),
        onSelect: () => apply({ includeEventTypes: scope.value }),
    }))
}

function displaySubs(views: SubtypeOption[], current: string | undefined, apply: ApplyInsightFilter): SubOption[] {
    const active = current ?? ChartDisplayType.ActionsLineGraph
    return views.map((view) => ({
        key: view.value,
        label: view.label,
        active: active === view.value,
        onSelect: () => apply({ display: view.value }),
    }))
}

function exampleSub(extraKey: string): SubOption {
    const entry = EXTRA_TYPES.find((candidate) => candidate.key === extraKey)
    return {
        key: extraKey,
        label: entry?.name ?? extraKey,
        disabledReason: entry?.disabledReason ?? 'Display-only in this prototype',
    }
}

// --- Variant E: flat tile row + "View as" display row ---

function TypeTile({
    name,
    icon: Icon,
    selected,
    onClick,
    disabledReason,
}: {
    name: string
    icon: React.ComponentType<any>
    selected: boolean
    onClick?: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <Tooltip title={disabledReason ? `${name}: ${disabledReason}` : name} placement="top">
            <button
                type="button"
                aria-pressed={selected}
                aria-label={name}
                onClick={disabledReason ? undefined : onClick}
                className={clsx(
                    'flex h-8 w-8 items-center justify-center rounded-md border text-base transition-colors',
                    selected
                        ? 'border-accent bg-surface-primary text-accent shadow-sm'
                        : 'text-secondary border-transparent',
                    disabledReason ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
                    !disabledReason && !selected && 'hover:bg-surface-primary hover:text-primary'
                )}
                data-attr={`prototype-insight-type-tile-${name.toLowerCase().replace(/\s+/g, '-')}`}
            >
                <Icon />
            </button>
        </Tooltip>
    )
}

function TypeAndViewCard(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const { display, funnelsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const meta = INSIGHT_TYPES_METADATA[activeView] ?? INSIGHT_TYPES_METADATA[InsightType.TRENDS]

    let viewOptions: SubtypeOption[] | null = null
    let viewValue: string | null = null
    let onViewChange: ((value: string) => void) | null = null
    if (activeView === InsightType.TRENDS || activeView === InsightType.STICKINESS) {
        viewOptions = activeView === InsightType.TRENDS ? TRENDS_VIEWS : STICKINESS_VIEWS
        viewValue = (display as string | undefined) ?? ChartDisplayType.ActionsLineGraph
        onViewChange = (value) => updateInsightFilter({ display: value as ChartDisplayType })
    } else if (activeView === InsightType.FUNNELS) {
        viewOptions = FUNNEL_VIEWS
        viewValue = (funnelsFilter?.funnelVizType as string | undefined) ?? FunnelVizType.Steps
        onViewChange = (value) => updateInsightFilter({ funnelVizType: value as FunnelVizType })
    }

    return (
        <CardShell>
            <CardLabel>Insight type</CardLabel>
            <div className="mt-2 flex flex-wrap gap-1">
                {CORE_TYPES.map((type) => (
                    <TypeTile
                        key={type}
                        name={INSIGHT_TYPES_METADATA[type].name}
                        icon={INSIGHT_TYPES_METADATA[type].icon}
                        selected={type === activeView}
                        onClick={() => setActiveView(type)}
                    />
                ))}
                <div className="border-accent mx-1 my-1 w-px self-stretch border-l opacity-40" />
                {EXTRA_TYPES.map((entry) => (
                    <TypeTile
                        key={entry.key}
                        name={entry.name}
                        icon={entry.icon}
                        selected={false}
                        disabledReason={entry.disabledReason}
                    />
                ))}
            </div>
            <div className="mt-2">
                <div className="text-sm font-semibold">{meta.name}</div>
                <div className="text-secondary text-xs">{meta.description}</div>
            </div>
            {viewOptions && onViewChange && (
                <div className="mt-3">
                    <CardLabel>View as</CardLabel>
                    <LemonSegmentedButton
                        size="xsmall"
                        fullWidth
                        className="mt-1"
                        value={viewValue ?? undefined}
                        onChange={(value) => onViewChange(value)}
                        options={viewOptions.map((option) => ({ value: option.value, label: option.label }))}
                    />
                </div>
            )}
        </CardShell>
    )
}

// --- Variants F and G: family tiles + method row, two competing groupings ---

interface FamilyDef {
    key: string
    name: string
    hint: string
    types: InsightType[]
}

const QUESTION_FAMILIES: FamilyDef[] = [
    { key: 'trends', name: 'Trends', hint: 'How much and how often?', types: [InsightType.TRENDS] },
    { key: 'funnel', name: 'Funnel', hint: 'Do users convert?', types: [InsightType.FUNNELS] },
    {
        key: 'retention',
        name: 'Retention',
        hint: 'Do users come back?',
        types: [InsightType.RETENTION, InsightType.STICKINESS, InsightType.LIFECYCLE],
    },
    { key: 'paths', name: 'Paths', hint: 'Where do users go?', types: [InsightType.PATHS] },
]

const CONFIG_FAMILIES: FamilyDef[] = [
    {
        key: 'trends',
        name: 'Trends',
        hint: 'Series over time',
        types: [InsightType.TRENDS, InsightType.STICKINESS, InsightType.LIFECYCLE],
    },
    { key: 'funnel', name: 'Funnel', hint: 'A sequence of steps', types: [InsightType.FUNNELS] },
    { key: 'retention', name: 'Retention', hint: 'Cohorts coming back', types: [InsightType.RETENTION] },
    { key: 'paths', name: 'Paths', hint: 'Flows between events', types: [InsightType.PATHS] },
]

function FamilyTile({
    name,
    hint,
    icon: Icon,
    selected,
    onClick,
}: {
    name: string
    hint: string
    icon: React.ComponentType<any>
    selected: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            aria-pressed={selected}
            onClick={onClick}
            className={clsx(
                'flex cursor-pointer flex-col items-start gap-0.5 rounded-md border p-2 text-left transition-colors',
                selected ? 'border-accent bg-surface-primary shadow-sm' : 'hover:bg-surface-primary border-transparent'
            )}
            data-attr={`prototype-insight-family-${name.toLowerCase()}`}
        >
            <span className={clsx('flex items-center gap-1.5 text-sm font-semibold', selected && 'text-accent')}>
                <Icon />
                {name}
            </span>
            <span className="text-secondary text-xs">{hint}</span>
        </button>
    )
}

interface FamilySelection {
    families: FamilyDef[]
    family: FamilyDef
    subs: SubOption[]
    activeMeta: InsightTypeMetadata
    selectFamily: (candidate: FamilyDef) => void
}

/** Shared state for the family-based variants: the active family, its method row, and the switch action. */
function useFamilySelection(grouping: 'questions' | 'config'): FamilySelection {
    const { insightProps } = useValues(insightLogic)
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const { funnelsFilter, retentionFilter, pathsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const apply = updateInsightFilter as unknown as ApplyInsightFilter

    const families = grouping === 'questions' ? QUESTION_FAMILIES : CONFIG_FAMILIES
    const family = families.find((candidate) => candidate.types.includes(activeView)) ?? families[0]

    const typeSub = (type: InsightType, label: string): SubOption => ({
        key: type,
        label,
        active: activeView === type,
        onSelect: () => setActiveView(type),
    })

    let subs: SubOption[]
    if (family.key === 'funnel') {
        subs = funnelVizSubs(funnelsFilter?.funnelVizType, apply)
    } else if (family.key === 'retention') {
        subs =
            grouping === 'questions'
                ? [
                      typeSub(InsightType.RETENTION, 'Retention curve'),
                      typeSub(InsightType.STICKINESS, 'Stickiness'),
                      typeSub(InsightType.LIFECYCLE, 'Lifecycle'),
                  ]
                : retentionTypeSubs(retentionFilter?.retentionType, apply)
    } else if (family.key === 'paths') {
        subs =
            grouping === 'config'
                ? [...pathScopeSubs(pathsFilter?.includeEventTypes, apply), exampleSub('EXAMPLE_SANKEY')]
                : [{ key: 'paths', label: 'User paths', active: true }, exampleSub('EXAMPLE_SANKEY')]
    } else {
        subs =
            grouping === 'questions'
                ? [
                      {
                          key: 'volume',
                          label: 'Volume',
                          active: activeView === InsightType.TRENDS,
                          onSelect: () => setActiveView(InsightType.TRENDS),
                      },
                      exampleSub('CALENDAR_HEATMAP'),
                      exampleSub('EXAMPLE_ANOMALY'),
                  ]
                : [
                      typeSub(InsightType.TRENDS, 'Volume'),
                      typeSub(InsightType.STICKINESS, 'Stickiness'),
                      typeSub(InsightType.LIFECYCLE, 'Lifecycle'),
                      exampleSub('CALENDAR_HEATMAP'),
                  ]
    }

    const activeMeta = INSIGHT_TYPES_METADATA[activeView] ?? INSIGHT_TYPES_METADATA[InsightType.TRENDS]

    const selectFamily = (candidate: FamilyDef): void => {
        if (!candidate.types.includes(activeView)) {
            setActiveView(candidate.types[0])
        }
    }

    return { families, family, subs, activeMeta, selectFamily }
}

function FamilyCard({ grouping }: { grouping: 'questions' | 'config' }): JSX.Element {
    const { families, family, subs, activeMeta, selectFamily } = useFamilySelection(grouping)

    return (
        <CardShell>
            <CardLabel>Insight type</CardLabel>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
                {families.map((candidate) => {
                    const Icon = INSIGHT_TYPES_METADATA[candidate.types[0]].icon
                    return (
                        <FamilyTile
                            key={candidate.key}
                            name={candidate.name}
                            hint={candidate.hint}
                            icon={Icon}
                            selected={candidate.key === family.key}
                            onClick={() => selectFamily(candidate)}
                        />
                    )
                })}
            </div>
            <div className="mt-3">
                <CardLabel>Method</CardLabel>
                <SubChips options={subs} dataAttrPrefix="prototype-insight-method" />
            </div>
            <div className="text-secondary mt-2 text-xs">{activeMeta.description}</div>
            <div className="border-primary text-secondary mt-3 border-t pt-2 text-[0.625rem]">
                {grouping === 'questions'
                    ? 'Grouped by question. Stickiness and lifecycle live under retention. SQL and custom queries move to the New insight menu.'
                    : 'Grouped by shared setup. Stickiness and lifecycle live under trends and keep your series when you switch. SQL and custom queries move to the New insight menu.'}
            </div>
        </CardShell>
    )
}

// --- Variant H: flat six types in a select + a uniform mode row, no regrouping ---

function FlatModesCard(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const { display, funnelsFilter, retentionFilter, pathsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const apply = updateInsightFilter as unknown as ApplyInsightFilter

    const typeOptions: LemonSelectOptions<string> = [
        {
            title: 'Insight type',
            options: CORE_TYPES.map((type) => {
                const meta = INSIGHT_TYPES_METADATA[type]
                const Icon = meta.icon
                return { value: type as string, label: meta.name, icon: <Icon /> }
            }),
        },
        {
            title: 'More types',
            options: EXTRA_TYPES.map((entry) => {
                const Icon = entry.icon
                return { value: entry.key, label: entry.name, icon: <Icon />, disabledReason: entry.disabledReason }
            }),
        },
    ]

    let modeSubs: SubOption[] | null = null
    if (activeView === InsightType.TRENDS) {
        modeSubs = displaySubs(TRENDS_VIEWS, display ?? undefined, apply)
    } else if (activeView === InsightType.STICKINESS) {
        modeSubs = displaySubs(STICKINESS_VIEWS, display ?? undefined, apply)
    } else if (activeView === InsightType.FUNNELS) {
        modeSubs = funnelVizSubs(funnelsFilter?.funnelVizType, apply)
    } else if (activeView === InsightType.RETENTION) {
        modeSubs = retentionTypeSubs(retentionFilter?.retentionType, apply)
    } else if (activeView === InsightType.PATHS) {
        modeSubs = pathScopeSubs(pathsFilter?.includeEventTypes, apply)
    }

    const activeMeta = INSIGHT_TYPES_METADATA[activeView] ?? INSIGHT_TYPES_METADATA[InsightType.TRENDS]

    return (
        <CardShell>
            <CardLabel>Insight type</CardLabel>
            <div className="mt-1">
                <LemonSelect
                    size="small"
                    fullWidth
                    value={activeView as string}
                    onChange={(value) => value && setActiveView(value as InsightType)}
                    options={typeOptions}
                    data-attr="prototype-insight-type-flat-select"
                />
            </div>
            {modeSubs && (
                <div className="mt-3">
                    <CardLabel>Mode</CardLabel>
                    <SubChips options={modeSubs} dataAttrPrefix="prototype-insight-mode" />
                </div>
            )}
            <div className="text-secondary mt-2 text-xs">{activeMeta.description}</div>
        </CardShell>
    )
}

// --- Variants I, J, K: visual alternatives. Same shared-setup grouping as G; only the looks change. ---

const FAMILY_SKETCHES: Record<string, () => JSX.Element> = {
    trends: TrendsSketch,
    funnel: FunnelSketch,
    retention: RetentionSketch,
    paths: PathsSketch,
}

function MutedLabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-secondary text-[0.625rem] font-semibold tracking-wide uppercase">{children}</div>
}

/** Variant I: sketch gallery. A plain surface card where the chart sketches carry the visual weight. */
function SketchGalleryCard(): JSX.Element {
    const { families, family, subs, activeMeta, selectFamily } = useFamilySelection('config')

    return (
        <div
            className="border-primary bg-surface-primary mb-3 rounded-lg border p-3"
            data-attr="prototype-insight-type-sketch-card"
        >
            <MutedLabel>Insight type</MutedLabel>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
                {families.map((candidate) => {
                    const Sketch = FAMILY_SKETCHES[candidate.key] ?? GenericInsightSketch
                    const selected = candidate.key === family.key
                    return (
                        <button
                            key={candidate.key}
                            type="button"
                            aria-pressed={selected}
                            onClick={() => selectFamily(candidate)}
                            className={clsx(
                                'cursor-pointer rounded-md border p-1.5 text-left transition-colors',
                                selected
                                    ? 'border-accent bg-accent-highlight-secondary shadow-sm'
                                    : 'border-primary hover:border-accent'
                            )}
                            data-attr={`prototype-insight-sketch-${candidate.key}`}
                        >
                            <Sketch />
                            <div
                                className={clsx(
                                    'mt-1 text-xs font-semibold',
                                    selected ? 'text-accent' : 'text-primary'
                                )}
                            >
                                {candidate.name}
                            </div>
                        </button>
                    )
                })}
            </div>
            <div className="mt-3">
                <MutedLabel>Method</MutedLabel>
                <SubChips options={subs} dataAttrPrefix="prototype-insight-sketch-method" />
            </div>
            <div className="text-secondary mt-2 text-xs">{activeMeta.description}</div>
        </div>
    )
}

/** Variant J: quiet list. No card chrome; families as rows, methods indented under the active one. */
function QuietListCard(): JSX.Element {
    const { families, family, subs, activeMeta, selectFamily } = useFamilySelection('config')

    return (
        <div className="border-primary mb-3 border-b pb-3" data-attr="prototype-insight-type-list">
            <MutedLabel>Insight type</MutedLabel>
            <div className="mt-1 flex flex-col">
                {families.map((candidate) => {
                    const Icon = INSIGHT_TYPES_METADATA[candidate.types[0]].icon
                    const selected = candidate.key === family.key
                    return (
                        <div key={candidate.key}>
                            <button
                                type="button"
                                aria-pressed={selected}
                                onClick={() => selectFamily(candidate)}
                                className={clsx(
                                    'flex w-full cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-left text-sm transition-colors',
                                    selected
                                        ? 'text-primary font-semibold'
                                        : 'text-secondary hover:bg-surface-primary hover:text-primary'
                                )}
                                data-attr={`prototype-insight-list-${candidate.key}`}
                            >
                                <Icon className={clsx(selected && 'text-accent')} />
                                {candidate.name}
                            </button>
                            {selected && (
                                <div className="border-primary mt-0.5 mb-1 ml-3 flex flex-col gap-0.5 border-l pl-3">
                                    {subs.map((option) => {
                                        const row = (
                                            <button
                                                key={option.key}
                                                type="button"
                                                aria-pressed={option.active}
                                                onClick={option.disabledReason ? undefined : option.onSelect}
                                                className={clsx(
                                                    'w-fit rounded px-1 py-0.5 text-left text-xs transition-colors',
                                                    option.active
                                                        ? 'text-accent font-semibold'
                                                        : 'text-secondary hover:text-primary',
                                                    option.disabledReason
                                                        ? 'cursor-not-allowed opacity-50'
                                                        : 'cursor-pointer'
                                                )}
                                                data-attr={`prototype-insight-list-method-${option.key.toLowerCase()}`}
                                            >
                                                {option.label}
                                            </button>
                                        )
                                        return option.disabledReason ? (
                                            <Tooltip key={option.key} title={option.disabledReason} placement="right">
                                                {row}
                                            </Tooltip>
                                        ) : (
                                            row
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
            <div className="text-secondary mt-1 text-xs">{activeMeta.description}</div>
        </div>
    )
}

/** Variant K: compact toolbar. Family and method as two bare selects on one row, no decoration. */
function CompactSelectsCard(): JSX.Element {
    const { families, family, subs, selectFamily } = useFamilySelection('config')

    const familyOptions: LemonSelectOptions<string> = families.map((candidate) => {
        const Icon = INSIGHT_TYPES_METADATA[candidate.types[0]].icon
        return { value: candidate.key, label: candidate.name, icon: <Icon /> }
    })
    const methodOptions: LemonSelectOptions<string | null> = subs.map((option) => ({
        value: option.key,
        label: option.label,
        disabledReason: option.disabledReason,
    }))
    const methodValue = subs.find((option) => option.active)?.key ?? null

    return (
        <div className="mb-3 flex flex-wrap items-center gap-1.5" data-attr="prototype-insight-type-compact">
            <LemonSelect
                size="small"
                value={family.key}
                onChange={(value) => {
                    const candidate = families.find((entry) => entry.key === value)
                    if (candidate) {
                        selectFamily(candidate)
                    }
                }}
                options={familyOptions}
                dropdownMatchSelectWidth={false}
                data-attr="prototype-insight-compact-family"
            />
            <LemonSelect<string | null>
                size="small"
                placeholder="Method"
                value={methodValue}
                onChange={(value) => {
                    subs.find((option) => option.key === value)?.onSelect?.()
                }}
                options={methodOptions}
                dropdownMatchSelectWidth={false}
                data-attr="prototype-insight-compact-method"
            />
        </div>
    )
}

// --- Variant L: a native "Visualization" section among General/Filters ---
// The top level is what you see (the display menu's groups promoted), not the query type:
// time series and total value and world map and calendar heatmap are all trends underneath.

const TIME_SERIES_DISPLAYS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line chart' },
    { value: ChartDisplayType.ActionsAreaGraph, label: 'Area chart' },
    { value: ChartDisplayType.ActionsUnstackedBar, label: 'Bar chart' },
    { value: ChartDisplayType.ActionsBar, label: 'Stacked bar' },
    { value: ChartDisplayType.ActionsLineGraphCumulative, label: 'Line (cumulative)' },
]

const TOTAL_VALUE_DISPLAYS: SubtypeOption[] = [
    { value: ChartDisplayType.BoldNumber, label: 'Number' },
    { value: ChartDisplayType.ActionsPie, label: 'Pie chart' },
    { value: ChartDisplayType.ActionsBarValue, label: 'Bar chart' },
    { value: ChartDisplayType.ActionsTable, label: 'Table' },
]

const LINE_BAR_DISPLAYS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line chart' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar chart' },
]

interface VisRow {
    key: string
    label: string
    icon: React.ComponentType<any>
    active: boolean
    onSelect: () => void
    disabledReason?: string
    subs: SubOption[]
}

function PrototypeVisualizationOptions({ insightProps }: EditorFilterProps): JSX.Element {
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const { display, funnelsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const apply = updateInsightFilter as unknown as ApplyInsightFilter

    const trendsDisplay = activeView === InsightType.TRENDS ? (display ?? ChartDisplayType.ActionsLineGraph) : null
    const isTotalValue = TOTAL_VALUE_DISPLAYS.some((option) => option.value === trendsDisplay)

    // Switching the type rebuilds the query in the same tick, so a display update aimed at a
    // not-yet-active trends query has to wait for the rebuilt query to land.
    const setTrendsDisplay = (value: ChartDisplayType): void => {
        if (activeView === InsightType.TRENDS) {
            apply({ display: value })
        } else {
            setActiveView(InsightType.TRENDS)
            window.setTimeout(() => apply({ display: value }), 0)
        }
    }

    const displaySubsFor = (views: SubtypeOption[], fallback: ChartDisplayType): SubOption[] =>
        views.map((view) => ({
            key: view.value,
            label: view.label,
            active: (display ?? fallback) === view.value,
            onSelect: () => apply({ display: view.value }),
        }))

    const funnelViz = funnelsFilter?.funnelVizType ?? FunnelVizType.Steps
    const funnelLayout = funnelsFilter?.layout ?? FunnelLayout.vertical
    const heatmapEnabled = !!featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT]

    const rows: VisRow[] = [
        {
            key: 'time-series',
            label: 'Time series',
            icon: INSIGHT_TYPES_METADATA[InsightType.TRENDS].icon,
            active:
                trendsDisplay !== null &&
                !isTotalValue &&
                trendsDisplay !== ChartDisplayType.WorldMap &&
                trendsDisplay !== ChartDisplayType.CalendarHeatmap,
            onSelect: () => setTrendsDisplay(ChartDisplayType.ActionsLineGraph),
            subs: displaySubsFor(TIME_SERIES_DISPLAYS, ChartDisplayType.ActionsLineGraph),
        },
        {
            key: 'total-value',
            label: 'Total value',
            icon: Icon123,
            active: isTotalValue,
            onSelect: () => setTrendsDisplay(ChartDisplayType.BoldNumber),
            subs: displaySubsFor(TOTAL_VALUE_DISPLAYS, ChartDisplayType.BoldNumber),
        },
        {
            key: 'world-map',
            label: 'World map',
            icon: IconGlobe,
            active: trendsDisplay === ChartDisplayType.WorldMap,
            onSelect: () => setTrendsDisplay(ChartDisplayType.WorldMap),
            subs: [],
        },
        {
            key: 'calendar-heatmap',
            label: 'Calendar heatmap',
            icon: QUERY_TYPES_METADATA[NodeKind.CalendarHeatmapQuery].icon,
            active: trendsDisplay === ChartDisplayType.CalendarHeatmap,
            onSelect: () => setTrendsDisplay(ChartDisplayType.CalendarHeatmap),
            disabledReason: heatmapEnabled
                ? undefined
                : 'Behind the calendar-heatmap-insight feature flag; enable it to try this',
            subs: [],
        },
        {
            key: 'funnel',
            label: 'Funnel',
            icon: INSIGHT_TYPES_METADATA[InsightType.FUNNELS].icon,
            active: activeView === InsightType.FUNNELS,
            onSelect: () => setActiveView(InsightType.FUNNELS),
            subs: [
                {
                    key: 'left-to-right',
                    label: 'Left to right',
                    active: funnelViz === FunnelVizType.Steps && funnelLayout === FunnelLayout.vertical,
                    onSelect: () => apply({ funnelVizType: FunnelVizType.Steps, layout: FunnelLayout.vertical }),
                },
                {
                    key: 'top-to-bottom',
                    label: 'Top to bottom',
                    active: funnelViz === FunnelVizType.Steps && funnelLayout === FunnelLayout.horizontal,
                    onSelect: () => apply({ funnelVizType: FunnelVizType.Steps, layout: FunnelLayout.horizontal }),
                },
                {
                    key: 'funnel-trends',
                    label: 'Trends',
                    active: funnelViz === FunnelVizType.Trends,
                    onSelect: () => apply({ funnelVizType: FunnelVizType.Trends }),
                },
                {
                    key: 'time-to-convert',
                    label: 'Time to convert',
                    active: funnelViz === FunnelVizType.TimeToConvert,
                    onSelect: () => apply({ funnelVizType: FunnelVizType.TimeToConvert }),
                },
            ],
        },
        {
            key: 'retention',
            label: 'Retention',
            icon: INSIGHT_TYPES_METADATA[InsightType.RETENTION].icon,
            active: activeView === InsightType.RETENTION,
            onSelect: () => setActiveView(InsightType.RETENTION),
            subs: displaySubsFor(LINE_BAR_DISPLAYS, ChartDisplayType.ActionsLineGraph),
        },
        {
            key: 'paths',
            label: 'User paths',
            icon: INSIGHT_TYPES_METADATA[InsightType.PATHS].icon,
            active: activeView === InsightType.PATHS,
            onSelect: () => setActiveView(InsightType.PATHS),
            subs: [],
        },
        {
            key: 'stickiness',
            label: 'Stickiness',
            icon: INSIGHT_TYPES_METADATA[InsightType.STICKINESS].icon,
            active: activeView === InsightType.STICKINESS,
            onSelect: () => setActiveView(InsightType.STICKINESS),
            subs: displaySubsFor(LINE_BAR_DISPLAYS, ChartDisplayType.ActionsLineGraph),
        },
        {
            key: 'lifecycle',
            label: 'Lifecycle',
            icon: INSIGHT_TYPES_METADATA[InsightType.LIFECYCLE].icon,
            active: activeView === InsightType.LIFECYCLE,
            onSelect: () => setActiveView(InsightType.LIFECYCLE),
            subs: [],
        },
    ]

    return (
        <div className="flex flex-col gap-0.5">
            {rows.map((row) => {
                const RowIcon = row.icon
                return (
                    <div key={row.key}>
                        <LemonButton
                            fullWidth
                            size="small"
                            active={row.active}
                            icon={<RowIcon />}
                            onClick={row.active ? undefined : row.onSelect}
                            disabledReason={row.disabledReason}
                            data-attr={`prototype-insight-vis-${row.key}`}
                        >
                            {row.label}
                        </LemonButton>
                        {row.active && row.subs.length > 0 && (
                            <div className="border-primary mt-0.5 mb-1 ml-3.5 border-l pl-2">
                                <SubChips options={row.subs} dataAttrPrefix={`prototype-insight-vis-${row.key}`} />
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

function PrototypeVisualizationSection(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const group: InsightEditorFilterGroup = {
        title: 'Visualization',
        defaultExpanded: true,
        editorFilters: [{ key: 'prototype-visualization', component: PrototypeVisualizationOptions }],
    }

    return (
        <div className="mb-3">
            <EditorFilterGroup editorFilterGroup={group} insightProps={insightProps} />
        </div>
    )
}

/** Routes the sidebar card variants; inert unless the URL requests one. */
export function SidebarTypeCardPrototype(): JSX.Element | null {
    const { searchParams } = useValues(router)
    const variant = typeof searchParams.variant === 'string' ? searchParams.variant : ''

    if (variant === 'sidebar') {
        return <TypeAndViewCard />
    }
    if (variant === 'sidebar-questions') {
        return <FamilyCard grouping="questions" />
    }
    if (variant === 'sidebar-families') {
        return <FamilyCard grouping="config" />
    }
    if (variant === 'sidebar-modes') {
        return <FlatModesCard />
    }
    if (variant === 'sidebar-sketches') {
        return <SketchGalleryCard />
    }
    if (variant === 'sidebar-list') {
        return <QuietListCard />
    }
    if (variant === 'sidebar-compact') {
        return <CompactSelectsCard />
    }
    if (variant === 'sidebar-section') {
        return <PrototypeVisualizationSection />
    }
    return null
}

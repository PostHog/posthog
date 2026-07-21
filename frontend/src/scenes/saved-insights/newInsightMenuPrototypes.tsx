import { useValues } from 'kea'
import { router } from 'kea-router'
// PROTOTYPE - throwaway, do not ship.
// Five variants of the "new insight" picker on /insights, switchable via `?variant=`:
//   A - flat grid (baseline from the first prototype commit)
//   B - flat grid with sub-insight chips on the Trends card
//   C - grid grouped by the question being asked
//   D - flat grid plus a "start from a preset" row
//   E - two-step: pick a question, then a visualization
//   F - like C, but airier: more whitespace and a description per section
// Cycle with the floating bar at the bottom of the screen (arrow keys work too).
import { useEffect, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconGlobe, IconPieChart, IconSparkles } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightType } from '~/types'

import {
    AiSketch,
    BarValueSketch,
    GenericInsightSketch,
    INSIGHT_TYPE_SKETCHES,
    NumberSketch,
    PieSketch,
    TableSketch,
    WorldMapSketch,
} from './InsightTypeSketch'

export type NewInsightPickerVariant = 'A' | 'B' | 'C' | 'D' | 'E' | 'F'

export interface PickerCardSpec {
    key: string
    name: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    iconClassName?: string
    sketch: () => JSX.Element
    to: string
    dataAttr: string
    onClick?: () => void
}

// -- Preset queries (trends sub-insights seeded with opinionated defaults) --

function trendsPresetUrl(overrides: Partial<TrendsQuery>): string {
    const query: InsightVizNode<TrendsQuery> = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: BaseMathType.TotalCount,
                },
            ],
            trendsFilter: {},
            ...overrides,
        },
    }
    return urls.insightNew({ query })
}

const uniqueUsersSeries = [
    {
        kind: NodeKind.EventsNode as const,
        event: '$pageview',
        name: '$pageview',
        math: BaseMathType.UniqueUsers,
    },
]

const PRESET_URLS = {
    worldMap: trendsPresetUrl({
        series: uniqueUsersSeries,
        trendsFilter: { display: ChartDisplayType.WorldMap },
        breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
    }),
    table: trendsPresetUrl({
        trendsFilter: { display: ChartDisplayType.ActionsTable },
        breakdownFilter: { breakdown: '$pathname', breakdown_type: 'event' },
    }),
    number: trendsPresetUrl({
        series: uniqueUsersSeries,
        trendsFilter: { display: ChartDisplayType.BoldNumber },
    }),
    pie: trendsPresetUrl({
        series: uniqueUsersSeries,
        trendsFilter: { display: ChartDisplayType.ActionsPie },
        breakdownFilter: { breakdown: '$device_type', breakdown_type: 'event' },
    }),
    barValue: trendsPresetUrl({
        trendsFilter: { display: ChartDisplayType.ActionsBarValue },
        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
    }),
}

const SUB_INSIGHT_CARDS: Record<'worldMap' | 'table' | 'number' | 'pie' | 'barValue', PickerCardSpec> = {
    worldMap: {
        key: 'preset-world-map',
        name: 'World map',
        description: 'Unique users per country on a world map.',
        icon: IconGlobe,
        sketch: WorldMapSketch,
        to: PRESET_URLS.worldMap,
        dataAttr: 'new-insight-menu-preset-world-map',
    },
    table: {
        key: 'preset-table',
        name: 'Table',
        description: 'Totals ranked in a sortable table.',
        icon: IconTableChart,
        sketch: TableSketch,
        to: PRESET_URLS.table,
        dataAttr: 'new-insight-menu-preset-table',
    },
    number: {
        key: 'preset-number',
        name: 'Number',
        description: 'One big number for a single metric.',
        icon: Icon123,
        sketch: NumberSketch,
        to: PRESET_URLS.number,
        dataAttr: 'new-insight-menu-preset-number',
    },
    pie: {
        key: 'preset-pie',
        name: 'Pie chart',
        description: 'Share of a total, split by a breakdown.',
        icon: IconPieChart,
        sketch: PieSketch,
        to: PRESET_URLS.pie,
        dataAttr: 'new-insight-menu-preset-pie',
    },
    barValue: {
        key: 'preset-bar-value',
        name: 'Bar chart',
        description: 'Total values as horizontal bars.',
        icon: IconTableChart,
        sketch: BarValueSketch,
        to: PRESET_URLS.barValue,
        dataAttr: 'new-insight-menu-preset-bar-value',
    },
}

// -- Shared card + card sources --

export function PickerCard({ spec, className }: { spec: PickerCardSpec; className?: string }): JSX.Element {
    const Icon = spec.icon
    return (
        <Link
            to={spec.to}
            data-attr={spec.dataAttr}
            onClick={spec.onClick}
            className={cn(
                'flex flex-col overflow-hidden rounded border border-primary bg-surface-primary',
                'transition-all duration-100 hover:-translate-y-0.5 hover:border-accent hover:shadow-md',
                'focus-visible:border-accent',
                className
            )}
        >
            <div className="shrink-0 border-b border-primary bg-fill-secondary">
                <spec.sketch />
            </div>
            <div className="flex flex-1 flex-col gap-0.5 p-2">
                <div className="flex items-center gap-1.5">
                    <Icon className={cn('text-base shrink-0', spec.iconClassName ?? 'text-secondary')} />
                    <span className="text-sm font-semibold text-default">{spec.name}</span>
                </div>
                <span className="text-xs leading-snug text-secondary">{spec.description}</span>
            </div>
        </Link>
    )
}

const AI_CARD: PickerCardSpec = {
    key: 'ai',
    name: 'AI',
    description: 'Ask PostHog AI to create insights using natural language.',
    icon: IconSparkles,
    iconClassName: 'text-ai',
    sketch: AiSketch,
    to: urls.ai(),
    dataAttr: 'new-insight-menu-ai',
}

function usePickerCards(): {
    ai: PickerCardSpec
    ordered: PickerCardSpec[]
    byType: Partial<Record<InsightType, PickerCardSpec>>
} {
    const { featureFlags } = useValues(featureFlagLogic)

    const byType: Partial<Record<InsightType, PickerCardSpec>> = {}
    const ordered: PickerCardSpec[] = []
    for (const [insightType, metadata] of Object.entries(INSIGHT_TYPES_METADATA)) {
        if (
            !metadata.inMenu ||
            insightType === InsightType.JSON ||
            (!featureFlags[FEATURE_FLAGS.HOG] && insightType === InsightType.HOG)
        ) {
            continue
        }
        const spec: PickerCardSpec = {
            key: insightType,
            name: metadata.name,
            description: metadata.description ?? '',
            icon: metadata.icon,
            sketch: INSIGHT_TYPE_SKETCHES[insightType as InsightType] ?? GenericInsightSketch,
            to: INSIGHT_TYPE_URLS[insightType as InsightType],
            dataAttr: `new-insight-menu-${insightType.toLowerCase()}`,
            onClick: () => eventUsageLogic.actions.reportSavedInsightNewInsightClicked(insightType),
        }
        byType[insightType as InsightType] = spec
        ordered.push(spec)
    }
    return { ai: AI_CARD, ordered, byType }
}

// -- Variant A: flat grid (baseline) --

export function FlatGridVariant(): JSX.Element {
    const { ai, ordered } = usePickerCards()
    return (
        <div className="w-[42rem] max-w-[calc(100vw-1rem)] p-1" data-attr="new-insight-type-picker">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {[ai, ...ordered].map((spec) => (
                    <PickerCard key={spec.key} spec={spec} />
                ))}
            </div>
        </div>
    )
}

// -- Variant B: flat grid, Trends card grows sub-insight chips --

const TRENDS_CHIPS: { label: string; to: string; dataAttr: string }[] = [
    { label: 'Table', to: PRESET_URLS.table, dataAttr: 'new-insight-menu-chip-table' },
    { label: 'Map', to: PRESET_URLS.worldMap, dataAttr: 'new-insight-menu-chip-map' },
    { label: 'Number', to: PRESET_URLS.number, dataAttr: 'new-insight-menu-chip-number' },
    { label: 'Pie', to: PRESET_URLS.pie, dataAttr: 'new-insight-menu-chip-pie' },
]

function ChipCard({ spec }: { spec: PickerCardSpec }): JSX.Element {
    const Icon = spec.icon
    return (
        <div
            className={cn(
                'flex flex-col overflow-hidden rounded border border-primary bg-surface-primary',
                'transition-all duration-100 hover:-translate-y-0.5 hover:border-accent hover:shadow-md'
            )}
        >
            <Link to={spec.to} data-attr={spec.dataAttr} onClick={spec.onClick} className="flex flex-col">
                <div className="shrink-0 border-b border-primary bg-fill-secondary">
                    <spec.sketch />
                </div>
                <div className="flex flex-col gap-0.5 p-2 pb-1">
                    <div className="flex items-center gap-1.5">
                        <Icon className={cn('text-base shrink-0', spec.iconClassName ?? 'text-secondary')} />
                        <span className="text-sm font-semibold text-default">{spec.name}</span>
                    </div>
                    <span className="text-xs leading-snug text-secondary">{spec.description}</span>
                </div>
            </Link>
            <div className="flex flex-wrap gap-1 px-2 pb-2 pt-1">
                {TRENDS_CHIPS.map((chip) => (
                    <Link
                        key={chip.label}
                        to={chip.to}
                        data-attr={chip.dataAttr}
                        className="rounded-full border border-primary px-1.5 py-0.5 text-[11px] leading-none text-secondary hover:border-accent hover:text-accent"
                    >
                        {chip.label}
                    </Link>
                ))}
            </div>
        </div>
    )
}

export function VariantChipsVariant(): JSX.Element {
    const { ai, ordered } = usePickerCards()
    return (
        <div className="w-[42rem] max-w-[calc(100vw-1rem)] p-1" data-attr="new-insight-type-picker">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {[ai, ...ordered].map((spec) =>
                    spec.key === InsightType.TRENDS ? (
                        <ChipCard key={spec.key} spec={spec} />
                    ) : (
                        <PickerCard key={spec.key} spec={spec} />
                    )
                )}
            </div>
        </div>
    )
}

// -- Variants C + F: grouped by the question being asked --

interface QuestionSection {
    title: string
    description: string
    cards: PickerCardSpec[]
}

function useQuestionSections(): QuestionSection[] {
    const { ai, byType } = usePickerCards()
    const sections: { title: string; description: string; cards: (PickerCardSpec | undefined)[] }[] = [
        {
            title: 'How does it change over time?',
            description: 'Follow a metric across days, weeks, or months to spot trends and dips.',
            cards: [byType[InsightType.TRENDS], byType[InsightType.STICKINESS], byType[InsightType.LIFECYCLE]],
        },
        {
            title: 'What are the totals?',
            description: 'Add up a metric for a period and see what it is made of, or where it comes from.',
            cards: [
                SUB_INSIGHT_CARDS.number,
                SUB_INSIGHT_CARDS.table,
                SUB_INSIGHT_CARDS.pie,
                SUB_INSIGHT_CARDS.worldMap,
            ],
        },
        {
            title: 'How do users behave?',
            description: 'Follow users through conversion funnels, retention, and journeys in your product.',
            cards: [byType[InsightType.FUNNELS], byType[InsightType.RETENTION], byType[InsightType.PATHS]],
        },
        {
            title: 'Build your own',
            description: 'Write SQL against your data, or ask AI to build the insight for you.',
            cards: [byType[InsightType.SQL], byType[InsightType.HOG], ai],
        },
    ]
    return sections.map((section) => ({
        ...section,
        cards: section.cards.filter((spec): spec is PickerCardSpec => !!spec),
    }))
}

export function SectionedVariant(): JSX.Element {
    const sections = useQuestionSections()
    return (
        <div
            className="flex w-[42rem] max-w-[calc(100vw-1rem)] flex-col gap-3 overflow-y-auto p-1 max-h-[calc(100vh-10rem)]"
            data-attr="new-insight-type-picker"
        >
            {sections.map((section) => (
                <div key={section.title} className="flex flex-col gap-1.5">
                    <span className="px-1 text-xs font-semibold uppercase tracking-wide text-tertiary">
                        {section.title}
                    </span>
                    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                        {section.cards.map((spec) => (
                            <PickerCard key={spec.key} spec={spec} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export function SectionedAiryVariant(): JSX.Element {
    const sections = useQuestionSections()
    return (
        <div
            className="flex w-[44rem] max-w-[calc(100vw-1rem)] flex-col gap-6 overflow-y-auto p-4 max-h-[calc(100vh-10rem)]"
            data-attr="new-insight-type-picker"
        >
            {sections.map((section) => (
                <div key={section.title} className="flex flex-col gap-2.5">
                    <div className="flex flex-col gap-0.5">
                        <span className="text-sm font-semibold text-default">{section.title}</span>
                        <span className="text-xs text-secondary">{section.description}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                        {section.cards.map((spec) => (
                            <PickerCard key={spec.key} spec={spec} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

// -- Variant D: flat grid plus a "start from a preset" row --

const PRESET_ROWS: {
    key: string
    name: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    to: string
}[] = [
    {
        key: 'users-by-country',
        name: 'Users by country',
        description: 'World map of unique users.',
        icon: IconGlobe,
        to: PRESET_URLS.worldMap,
    },
    {
        key: 'top-pages',
        name: 'Top pages',
        description: 'Pageviews by path in a ranked table.',
        icon: IconTableChart,
        to: PRESET_URLS.table,
    },
    {
        key: 'daily-active-users',
        name: 'Daily active users',
        description: 'Unique users as one big number.',
        icon: Icon123,
        to: PRESET_URLS.number,
    },
    {
        key: 'traffic-by-device',
        name: 'Traffic by device',
        description: 'Pageviews by device type as a pie.',
        icon: IconPieChart,
        to: PRESET_URLS.pie,
    },
]

export function PresetsRowVariant(): JSX.Element {
    const { ai, ordered } = usePickerCards()
    return (
        <div className="w-[42rem] max-w-[calc(100vw-1rem)] p-1" data-attr="new-insight-type-picker">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {[ai, ...ordered].map((spec) => (
                    <PickerCard key={spec.key} spec={spec} />
                ))}
            </div>
            <LemonDivider className="my-2" />
            <span className="px-1 text-xs font-semibold uppercase tracking-wide text-tertiary">
                Or start from a preset
            </span>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
                {PRESET_ROWS.map((preset) => (
                    <Link
                        key={preset.key}
                        to={preset.to}
                        data-attr={`new-insight-menu-preset-${preset.key}`}
                        className="flex items-center gap-2 rounded border border-primary bg-surface-primary p-2 transition-all duration-100 hover:border-accent hover:shadow-sm"
                    >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded bg-fill-secondary">
                            <preset.icon className="text-lg text-secondary" />
                        </span>
                        <span className="flex flex-col">
                            <span className="text-sm font-semibold text-default">{preset.name}</span>
                            <span className="text-xs text-secondary">{preset.description}</span>
                        </span>
                    </Link>
                ))}
            </div>
        </div>
    )
}

// -- Variant E: two-step, question first then visualization --

interface PickerQuestion {
    key: string
    question: string
    hint: string
    /** Direct link when the question has exactly one answer. */
    to?: string
    options?: (PickerCardSpec | undefined)[]
}

export function TwoStepVariant(): JSX.Element {
    const { ai, byType } = usePickerCards()
    const [activeKey, setActiveKey] = useState<string | null>(null)

    const questions: PickerQuestion[] = [
        {
            key: 'over-time',
            question: 'How does a metric change over time?',
            hint: 'Trends · Stickiness · Lifecycle',
            options: [byType[InsightType.TRENDS], byType[InsightType.STICKINESS], byType[InsightType.LIFECYCLE]],
        },
        {
            key: 'totals',
            question: 'What are the totals and top values?',
            hint: 'Number · Table · Pie · Bar',
            options: [
                SUB_INSIGHT_CARDS.number,
                SUB_INSIGHT_CARDS.table,
                SUB_INSIGHT_CARDS.pie,
                SUB_INSIGHT_CARDS.barValue,
            ],
        },
        {
            key: 'where',
            question: 'Where in the world are my users?',
            hint: 'World map',
            to: PRESET_URLS.worldMap,
        },
        {
            key: 'convert',
            question: 'Do users complete a flow?',
            hint: 'Funnel',
            to: INSIGHT_TYPE_URLS[InsightType.FUNNELS],
        },
        {
            key: 'return',
            question: 'Do users come back?',
            hint: 'Retention · Stickiness',
            options: [byType[InsightType.RETENTION], byType[InsightType.STICKINESS], byType[InsightType.LIFECYCLE]],
        },
        {
            key: 'navigate',
            question: 'How do users move through the product?',
            hint: 'Paths',
            to: INSIGHT_TYPE_URLS[InsightType.PATHS],
        },
        {
            key: 'custom',
            question: 'Something else?',
            hint: 'SQL · AI',
            options: [byType[InsightType.SQL], byType[InsightType.HOG], ai],
        },
    ]

    const active = questions.find((question) => question.key === activeKey)

    if (active?.options) {
        return (
            <div className="w-[36rem] max-w-[calc(100vw-1rem)] p-1" data-attr="new-insight-type-picker">
                <div className="mb-2 flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronLeft />}
                        onClick={() => setActiveKey(null)}
                        data-attr="new-insight-menu-two-step-back"
                    />
                    <span className="text-sm font-semibold text-default">{active.question}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                    {active.options
                        .filter((spec): spec is PickerCardSpec => !!spec)
                        .map((spec) => (
                            <PickerCard key={spec.key} spec={spec} />
                        ))}
                </div>
            </div>
        )
    }

    return (
        <div className="flex w-[26rem] max-w-[calc(100vw-1rem)] flex-col gap-1 p-1" data-attr="new-insight-type-picker">
            {questions.map((question) => {
                const content = (
                    <>
                        <span className="flex flex-col text-left">
                            <span className="text-sm font-medium text-default">{question.question}</span>
                            <span className="text-xs text-secondary">{question.hint}</span>
                        </span>
                        <IconChevronRight className="shrink-0 text-secondary" />
                    </>
                )
                const rowClassName =
                    'flex w-full items-center justify-between gap-2 rounded border border-primary bg-surface-primary p-2 transition-all duration-100 hover:border-accent hover:shadow-sm'
                return question.to ? (
                    <Link
                        key={question.key}
                        to={question.to}
                        data-attr={`new-insight-menu-question-${question.key}`}
                        className={rowClassName}
                    >
                        {content}
                    </Link>
                ) : (
                    <button
                        key={question.key}
                        type="button"
                        data-attr={`new-insight-menu-question-${question.key}`}
                        className={rowClassName}
                        onClick={() => setActiveKey(question.key)}
                    >
                        {content}
                    </button>
                )
            })}
        </div>
    )
}

// -- Variant registry + floating switcher --

export const NEW_INSIGHT_PICKER_VARIANTS: {
    key: NewInsightPickerVariant
    name: string
    component: () => JSX.Element
}[] = [
    { key: 'A', name: 'Flat grid', component: FlatGridVariant },
    { key: 'B', name: 'Variant chips', component: VariantChipsVariant },
    { key: 'C', name: 'Grouped by question', component: SectionedVariant },
    { key: 'D', name: 'Grid + presets', component: PresetsRowVariant },
    { key: 'E', name: 'Two-step', component: TwoStepVariant },
    { key: 'F', name: 'Grouped by question (airy)', component: SectionedAiryVariant },
]

export function getPickerVariant(raw: unknown): NewInsightPickerVariant {
    return NEW_INSIGHT_PICKER_VARIANTS.some((variant) => variant.key === raw) ? (raw as NewInsightPickerVariant) : 'A'
}

export function PickerVariantSwitcher(): JSX.Element | null {
    const { searchParams, hashParams, location } = useValues(router)
    const current = getPickerVariant(searchParams['variant'])
    const index = NEW_INSIGHT_PICKER_VARIANTS.findIndex((variant) => variant.key === current)

    const cycle = (delta: number): void => {
        const next =
            NEW_INSIGHT_PICKER_VARIANTS[
                (index + delta + NEW_INSIGHT_PICKER_VARIANTS.length) % NEW_INSIGHT_PICKER_VARIANTS.length
            ]
        router.actions.replace(location.pathname, { ...searchParams, variant: next.key }, hashParams)
    }

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            cycle(event.key === 'ArrowLeft' ? -1 : 1)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    if (process.env.NODE_ENV === 'production') {
        return null
    }

    return (
        <div className="fixed bottom-4 left-1/2 z-[1100] flex -translate-x-1/2 items-center gap-1 rounded-full border border-primary bg-surface-primary py-1 pl-1 pr-3 shadow-lg">
            <LemonButton
                size="xsmall"
                icon={<IconChevronLeft />}
                onClick={() => cycle(-1)}
                tooltip="Previous variant (left arrow)"
            />
            <span className="whitespace-nowrap text-xs font-semibold text-default">
                <span className="mr-1 font-normal text-tertiary">Picker prototype</span>
                {current} · {NEW_INSIGHT_PICKER_VARIANTS[index].name}
            </span>
            <LemonButton
                size="xsmall"
                icon={<IconChevronRight />}
                onClick={() => cycle(1)}
                tooltip="Next variant (right arrow)"
            />
        </div>
    )
}

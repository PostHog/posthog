import { useValues } from 'kea'

import { IconPlusSmall, IconSparkles } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { IconInsightNumber, IconInsightPie, IconInsightTable, IconInsightWorldMap } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA, isInsightTypeCreatable } from 'scenes/saved-insights/insightTypesMetadata'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, BaseMathType, ChartDisplayType, InsightType } from '~/types'

import {
    AiSketch,
    GenericInsightSketch,
    INSIGHT_TYPE_SKETCHES,
    NumberSketch,
    PieSketch,
    TableSketch,
    WorldMapSketch,
} from './InsightTypeSketch'

interface NewInsightCardSpec {
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

// -- Preset queries: trends sub-insights seeded with opinionated defaults --

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

const TRENDS_PRESET_URLS = {
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
}

function reportNewInsightClicked(insightType: InsightType, presetKey?: string): void {
    eventUsageLogic.actions.reportSavedInsightNewInsightClicked(insightType, presetKey)
}

const SUB_INSIGHT_CARDS: Record<'worldMap' | 'table' | 'number' | 'pie', NewInsightCardSpec> = {
    worldMap: {
        key: 'preset-world-map',
        name: 'World map',
        description: 'Unique users per country.',
        icon: IconInsightWorldMap,
        sketch: WorldMapSketch,
        to: TRENDS_PRESET_URLS.worldMap,
        dataAttr: 'new-insight-menu-preset-world-map',
        onClick: () => reportNewInsightClicked(InsightType.TRENDS, 'world-map'),
    },
    table: {
        key: 'preset-table',
        name: 'Table',
        description: 'Totals ranked in a sortable table.',
        icon: IconInsightTable,
        sketch: TableSketch,
        to: TRENDS_PRESET_URLS.table,
        dataAttr: 'new-insight-menu-preset-table',
        onClick: () => reportNewInsightClicked(InsightType.TRENDS, 'table'),
    },
    number: {
        key: 'preset-number',
        name: 'Number',
        description: 'One big number for a single metric.',
        icon: IconInsightNumber,
        sketch: NumberSketch,
        to: TRENDS_PRESET_URLS.number,
        dataAttr: 'new-insight-menu-preset-number',
        onClick: () => reportNewInsightClicked(InsightType.TRENDS, 'number'),
    },
    pie: {
        key: 'preset-pie',
        name: 'Pie chart',
        description: 'Share of a total, split by a breakdown.',
        icon: IconInsightPie,
        sketch: PieSketch,
        to: TRENDS_PRESET_URLS.pie,
        dataAttr: 'new-insight-menu-preset-pie',
        onClick: () => reportNewInsightClicked(InsightType.TRENDS, 'pie'),
    },
}

const AI_CARD: NewInsightCardSpec = {
    key: 'ai',
    name: 'AI',
    description: 'Ask PostHog AI to create insights using natural language.',
    icon: IconSparkles,
    iconClassName: 'text-ai',
    sketch: AiSketch,
    to: urls.ai(),
    dataAttr: 'new-insight-menu-ai',
}

function useNewInsightCards(): {
    ai: NewInsightCardSpec
    byType: Partial<Record<InsightType, NewInsightCardSpec>>
} {
    const { featureFlags } = useValues(featureFlagLogic)

    const byType: Partial<Record<InsightType, NewInsightCardSpec>> = {}
    for (const [insightType, metadata] of Object.entries(INSIGHT_TYPES_METADATA)) {
        if (!isInsightTypeCreatable(metadata, featureFlags) || insightType === InsightType.JSON) {
            continue
        }
        const spec: NewInsightCardSpec = {
            key: insightType,
            name: metadata.name,
            description: metadata.description ?? '',
            icon: metadata.icon,
            sketch: INSIGHT_TYPE_SKETCHES[insightType as InsightType] ?? GenericInsightSketch,
            to: INSIGHT_TYPE_URLS[insightType as InsightType],
            dataAttr: `new-insight-menu-${insightType.toLowerCase()}`,
            onClick: () => reportNewInsightClicked(insightType as InsightType),
        }
        byType[insightType as InsightType] = spec
    }
    return { ai: AI_CARD, byType }
}

function NewInsightCard({
    spec,
    uniformHeight = false,
}: {
    spec: NewInsightCardSpec
    /** Reserve exactly two description lines so cards line up across sections. */
    uniformHeight?: boolean
}): JSX.Element {
    const Icon = spec.icon
    return (
        <Link
            to={spec.to}
            data-attr={spec.dataAttr}
            onClick={spec.onClick}
            className={cn(
                'flex flex-col overflow-hidden rounded border border-primary bg-surface-primary',
                'transition-all duration-100 hover:-translate-y-0.5 hover:border-accent hover:shadow-md',
                'focus-visible:border-accent'
            )}
        >
            <div className="shrink-0 border-b border-primary bg-fill-secondary">
                <spec.sketch />
            </div>
            <div className="flex flex-1 flex-col gap-0.5 p-2">
                <div className="flex items-center gap-1.5">
                    <Icon className={cn('text-base shrink-0', spec.iconClassName ?? 'text-secondary')} />
                    <span className="whitespace-nowrap text-sm font-semibold text-default">{spec.name}</span>
                </div>
                <span
                    className={cn('text-xs leading-snug text-secondary', uniformHeight && 'line-clamp-2 min-h-[33px]')}
                >
                    {spec.description}
                </span>
            </div>
        </Link>
    )
}

// -- Two columns of question-framed sections with a divider --

// Terse copy so every description fits the two-line slot at the card width
const SHORT_CARD_DESCRIPTIONS: Record<string, string> = {
    [InsightType.TRENDS]: 'How metrics change over time.',
    [InsightType.STICKINESS]: 'How often users repeat actions.',
    [InsightType.LIFECYCLE]: 'New, returning, and dormant users.',
    [InsightType.FUNNELS]: 'Conversion through a sequence of steps.',
    [InsightType.RETENTION]: 'How many users come back later.',
    [InsightType.PATHS]: 'The routes users take through your product.',
    [InsightType.JOURNEYS]: 'The steps users take and where they stop.',
    [InsightType.SQL]: 'Query your data with SQL.',
    [InsightType.HOG]: 'Query your data with Hog.',
    ai: 'Describe an insight and let AI build it.',
}

interface QuestionSection {
    title: string
    description: string
    cards: NewInsightCardSpec[]
}

function useQuestionSections(): QuestionSection[] {
    const { ai, byType } = useNewInsightCards()
    const sections: { title: string; description: string; cards: (NewInsightCardSpec | undefined)[] }[] = [
        {
            title: 'How does it change over time?',
            description: 'Follow a metric over time to spot trends and dips.',
            cards: [byType[InsightType.TRENDS], byType[InsightType.STICKINESS], byType[InsightType.LIFECYCLE]],
        },
        {
            title: 'What are the totals?',
            description: 'Add up a metric and see what it is made of.',
            cards: [
                SUB_INSIGHT_CARDS.number,
                SUB_INSIGHT_CARDS.table,
                SUB_INSIGHT_CARDS.pie,
                SUB_INSIGHT_CARDS.worldMap,
            ],
        },
        {
            title: 'How do users behave?',
            description: 'Funnels, retention, and journeys through your product.',
            cards: [
                byType[InsightType.FUNNELS],
                byType[InsightType.RETENTION],
                byType[InsightType.PATHS],
                byType[InsightType.JOURNEYS],
            ],
        },
        {
            title: 'Build your own',
            description: 'Write SQL against your data, or let AI build it.',
            cards: [byType[InsightType.SQL], byType[InsightType.HOG], ai],
        },
    ]
    return sections.map((section) => ({
        ...section,
        cards: section.cards.filter((spec): spec is NewInsightCardSpec => !!spec),
    }))
}

function QuestionSectionBlock({ section }: { section: QuestionSection }): JSX.Element {
    return (
        <div className="flex flex-col gap-2.5">
            {/* single-line title + description keep header heights equal, so card rows align across columns */}
            <div className="flex flex-col gap-0.5">
                <span className="truncate text-sm font-semibold text-default">{section.title}</span>
                <span className="truncate text-xs text-secondary">{section.description}</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
                {section.cards.map((spec) => (
                    <NewInsightCard
                        key={spec.key}
                        spec={{ ...spec, description: SHORT_CARD_DESCRIPTIONS[spec.key] ?? spec.description }}
                        uniformHeight
                    />
                ))}
            </div>
        </div>
    )
}

export function NewInsightMenuOverlay(): JSX.Element {
    const sections = useQuestionSections()
    const columns = [sections.slice(0, 2), sections.slice(2)]
    return (
        <div
            className="flex w-[58rem] max-w-[calc(100vw-1rem)] gap-4 overflow-y-auto p-4 max-h-[calc(100vh-10rem)]"
            data-attr="new-insight-menu"
        >
            <div className="flex flex-1 flex-col gap-6">
                {columns[0].map((section) => (
                    <QuestionSectionBlock key={section.title} section={section} />
                ))}
            </div>
            <LemonDivider vertical className="self-stretch" />
            <div className="flex flex-1 flex-col gap-6">
                {columns[1].map((section) => (
                    <QuestionSectionBlock key={section.title} section={section} />
                ))}
            </div>
        </div>
    )
}

export function NewInsightButton(): JSX.Element {
    const button = (
        <LemonButton
            type="primary"
            data-attr="saved-insights-new-insight-button"
            size="small"
            icon={<IconPlusSmall />}
            tooltip="New insight"
        >
            New
        </LemonButton>
    )

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Insight}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Shortcut
                name="NewInsight"
                keybind={[keyBinds.new]}
                intent="New insight"
                interaction="click"
                scope={Scene.SavedInsights}
                priority={100}
            >
                <LemonDropdown overlay={<NewInsightMenuOverlay />} placement="bottom-end">
                    {button}
                </LemonDropdown>
            </Shortcut>
        </AccessControlAction>
    )
}

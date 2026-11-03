import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconRewindPlay, IconWarning } from '@posthog/icons'
import { Badge } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import {
    AnyPropertyFilter,
    BehavioralEventType,
    EntityTypes,
    FilterLogicalOperator,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
    TimeUnitType,
    UniversalFiltersGroup,
} from '~/types'

import { FilterBar } from './FilterBar'
import { registerFilterBarCategory } from './filterBarCategories'
import { FilterBarDateRange } from './FilterBarDateRange'
import { FilterBarInterval } from './FilterBarInterval'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarOptionControl } from './FilterBarOptionControl'
import { filterBarStoryDecorator } from './filterBarStoryMocks'
import { FilterBarCategoryId } from './filterBarTypes'

/**
 * Common filter shapes from across PostHog, each fed to the filter bar. A scenario lists what the filters mean on
 * their home surface, so a reviewer can compare that with what the bar shows and find the gaps.
 */

const REPLAY_FIELDS: Record<string, { label: string; propertyType: PropertyType }> = {
    active_seconds: { label: 'Active duration', propertyType: PropertyType.Duration },
    visited_page: { label: 'Visited page', propertyType: PropertyType.String },
}

// How a surface adds its own filter type. Only this story's replay scenario lists the category in `categoryIds`.
registerFilterBarCategory({
    id: 'custom_recording',
    label: 'Recording',
    plural: 'recording properties',
    propertyFilterType: PropertyFilterType.Recording,
    tier: 'primary',
    icon: IconRewindPlay,
    fetchFields: (query) =>
        Object.entries(REPLAY_FIELDS)
            .filter(([, field]) => field.label.toLowerCase().includes(query.toLowerCase()))
            .map(([key, field]) => ({ categoryId: 'custom_recording', key, ...field })),
    fetchValues: (key) => (key === 'visited_page' ? ['/checkout', '/pricing'] : []),
    propertyType: (key) => REPLAY_FIELDS[key]?.propertyType ?? null,
    fieldLabel: (key) => REPLAY_FIELDS[key]?.label ?? key,
})

type Support = 'supported' | 'lossy' | 'unsupported' | 'needs-design'

interface Scenario {
    id: string
    surface: string
    title: string
    support: Support
    /** What the filters mean on their home surface, one condition per line. */
    meaning: string[]
    /** Why the bar falls short, for lossy and unsupported scenarios. */
    gap?: string
    /** A surface that stores flat filters passes this, and the bar can't build groups there. */
    filters?: AnyPropertyFilter[]
    /** A surface that stores groups passes this. */
    filterGroup?: UniversalFiltersGroup
    categoryIds?: FilterBarCategoryId[]
    withControls?: boolean
    withSeverityControl?: boolean
    /** Stands in for the count a real surface would query for and pass to `stackedFooter`. */
    matchCount?: string
}

const SUPPORT_BADGE: Record<Support, { label: string; variant: 'success' | 'warning' | 'destructive' | 'info' }> = {
    supported: { label: 'Supported', variant: 'success' },
    lossy: { label: 'Lossy', variant: 'warning' },
    unsupported: { label: 'Read-only', variant: 'destructive' },
    'needs-design': { label: 'Needs design', variant: 'info' },
}

const SCENARIOS: Scenario[] = [
    {
        id: 'dashboard',
        surface: 'Dashboards',
        title: 'Flat AND with dates and interval',
        support: 'supported',
        meaning: [
            'Browser is Chrome or Firefox',
            'AND email contains example.com',
            'AND person is in cohort Power users',
            'AND OS is set',
            'Last 30 days, by week',
        ],
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: ['Chrome', 'Firefox'],
            },
            {
                type: PropertyFilterType.Person,
                key: 'email',
                operator: PropertyOperator.IContains,
                value: 'example.com',
            },
            { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 1 },
            { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsSet, value: null },
        ],
        withControls: true,
    },
    {
        id: 'web-analytics',
        surface: 'Web analytics',
        title: 'Entry page, campaign and negation',
        support: 'supported',
        meaning: ['Entry page is /pricing', 'AND UTM source is google or newsletter', 'AND country is not FR'],
        filters: [
            {
                type: PropertyFilterType.Session,
                key: '$entry_pathname',
                operator: PropertyOperator.Exact,
                value: ['/pricing'],
            },
            {
                type: PropertyFilterType.Event,
                key: 'utm_source',
                operator: PropertyOperator.Exact,
                value: ['google', 'newsletter'],
            },
            {
                type: PropertyFilterType.Event,
                key: '$geoip_country_code',
                operator: PropertyOperator.IsNot,
                value: ['FR'],
            },
        ],
    },
    {
        id: 'numbers-and-dates',
        surface: 'Insights',
        title: 'Numeric comparisons and an absolute date',
        support: 'supported',
        meaning: [
            'Browser version is greater than 120',
            'AND session duration is greater than 60 seconds',
            'AND signed up after 2025-09-01',
        ],
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$browser_version',
                operator: PropertyOperator.GreaterThan,
                value: 120,
            },
            {
                type: PropertyFilterType.Session,
                key: '$session_duration',
                operator: PropertyOperator.GreaterThan,
                value: 60,
            },
            {
                type: PropertyFilterType.Person,
                key: 'signed_up_at',
                operator: PropertyOperator.IsDateAfter,
                value: '2025-09-01',
            },
        ],
    },
    {
        id: 'sql-and-elements',
        surface: 'Insights',
        title: 'SQL expression and autocapture element',
        support: 'supported',
        meaning: ["SQL: properties.$current_url LIKE '%/docs/%'", 'AND clicked element text is Sign up'],
        filters: [
            { type: PropertyFilterType.HogQL, key: "properties.$current_url LIKE '%/docs/%'" },
            { type: PropertyFilterType.Element, key: 'text', operator: PropertyOperator.Exact, value: ['Sign up'] },
        ],
    },
    {
        id: 'or-across-properties',
        surface: 'Insights, replay, error tracking, logs',
        title: 'OR across different properties',
        support: 'supported',
        meaning: ['Browser is Safari', 'OR country is FR'],
        filterGroup: {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Safari'],
                        },
                    ],
                },
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$geoip_country_code',
                            operator: PropertyOperator.Exact,
                            value: ['FR'],
                        },
                    ],
                },
            ],
        },
    },
    {
        id: 'or-cohorts',
        surface: 'Insights, cohorts',
        title: 'In any of two cohorts',
        support: 'supported',
        meaning: ['Person is in cohort Power users', 'OR person is in cohort Trial accounts'],
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 1 },
                        { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 2 },
                    ],
                },
            ],
        },
    },
    {
        id: 'two-level-groups',
        surface: 'Insights, cohorts',
        title: 'Two groups, each with its own AND/OR',
        support: 'supported',
        meaning: ['(Browser is Safari AND OS is iOS)', 'OR (Browser is Chrome AND OS is Android)'],
        filterGroup: {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Safari'],
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$os',
                            operator: PropertyOperator.Exact,
                            value: ['iOS'],
                        },
                    ],
                },
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Chrome'],
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$os',
                            operator: PropertyOperator.Exact,
                            value: ['Android'],
                        },
                    ],
                },
            ],
        },
    },
    {
        id: 'flag-condition-sets',
        surface: 'Feature flags, surveys',
        title: 'Condition sets with a rollout each',
        support: 'lossy',
        meaning: [
            'Set 1: email contains example.com, rolled out to 100%',
            'OR set 2: country is FR, rolled out to 20%',
        ],
        gap: 'A group can hold the conditions, but the bar has no place for a rollout percentage or a variant per set.',
        filters: [
            {
                type: PropertyFilterType.Person,
                key: 'email',
                operator: PropertyOperator.IContains,
                value: 'example.com',
            },
        ],
    },
    {
        id: 'relative-date',
        surface: 'Feature flags, surveys, cohorts, workflows',
        title: 'Relative date value',
        support: 'lossy',
        meaning: ['Signed up in the last 7 days (stored as -7d)'],
        gap: 'The date menu writes absolute dates only, so editing this value turns a rolling window into a fixed day.',
        filters: [
            {
                type: PropertyFilterType.Person,
                key: 'signed_up_at',
                operator: PropertyOperator.IsDateAfter,
                value: '-7d',
            },
        ],
    },
    {
        id: 'between',
        surface: 'Cohorts',
        title: 'Numeric between',
        support: 'lossy',
        meaning: ['Browser version is between 100 and 120'],
        gap: 'The bar has no between operator and no two-value input.',
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$browser_version',
                operator: PropertyOperator.Between,
                value: [100, 120],
            },
        ],
    },
    {
        id: 'replay',
        surface: 'Session replay',
        title: 'Recording duration and visited page, from a registered category',
        support: 'supported',
        meaning: ['Active duration is greater than 60 seconds', 'AND visited page /checkout'],
        categoryIds: ['events', 'event_properties', 'person_properties', 'custom_recording'],
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Recording,
                            key: 'active_seconds',
                            operator: PropertyOperator.GreaterThan,
                            value: 60,
                        },
                        {
                            type: PropertyFilterType.Recording,
                            key: 'visited_page',
                            operator: PropertyOperator.Exact,
                            value: ['/checkout'],
                        },
                    ],
                },
            ],
        },
    },
    {
        id: 'logs',
        surface: 'Logs, tracing',
        title: 'Log and resource attributes, with a severity control',
        support: 'unsupported',
        meaning: ['Attribute http.status_code is 500', 'AND resource service.name is api'],
        gap: 'No surface registers log attribute categories yet, so the chips stay read-only. The severity chip shows how a surface adds its own control.',
        filters: [
            {
                type: PropertyFilterType.LogAttribute,
                key: 'http.status_code',
                operator: PropertyOperator.Exact,
                value: ['500'],
            },
            {
                type: PropertyFilterType.LogResourceAttribute,
                key: 'service.name',
                operator: PropertyOperator.Exact,
                value: ['api'],
            },
        ],
        withSeverityControl: true,
    },
    {
        id: 'error-tracking',
        surface: 'Error tracking',
        title: 'Issue properties',
        support: 'unsupported',
        meaning: ['Issue name contains TypeError'],
        gap: 'No surface registers issue filters yet, so the chip stays read-only. Status, assignee and search would be controls that surface adds.',
        filters: [
            {
                type: PropertyFilterType.ErrorTrackingIssue,
                key: 'name',
                operator: PropertyOperator.IContains,
                value: 'TypeError',
            },
        ],
    },
    {
        id: 'data-warehouse',
        surface: 'Insights, CDP',
        title: 'Data warehouse property',
        support: 'unsupported',
        meaning: ['Stripe customer plan is enterprise'],
        gap: 'No surface registers data warehouse categories yet, so the chip stays read-only.',
        filters: [
            {
                type: PropertyFilterType.DataWarehouse,
                key: 'stripe_customer.plan',
                operator: PropertyOperator.Exact,
                value: ['enterprise'],
            },
        ],
    },
    {
        id: 'behavioral',
        surface: 'Insights, cohorts',
        title: 'Performed an event in a time window',
        support: 'unsupported',
        meaning: ['Person performed $pageview at least once in the last 30 days'],
        gap: 'The chip stays read-only. An editable one needs a count and a time window as well as the event.',
        filters: [
            {
                type: PropertyFilterType.Behavioral,
                key: '$pageview',
                value: BehavioralEventType.PerformEvent,
                event_type: 'events',
                time_value: 30,
                time_interval: TimeUnitType.Day,
            },
        ],
    },
    {
        id: 'feature-flag-dependency',
        surface: 'Feature flags, CDP',
        title: 'Flag dependency',
        support: 'unsupported',
        meaning: ['Flag new-checkout evaluates to true'],
        gap: 'The bar writes flags as $feature/ event properties. A surface can register the flag type to edit this one, and until then the chip stays read-only.',
        filters: [
            { type: PropertyFilterType.Flag, key: '42', operator: PropertyOperator.FlagEvaluatesTo, value: true },
        ],
    },
    {
        id: 'event-scoped',
        surface: 'Replay, insights, experiments, actions, workflows',
        title: 'Event with its own property filters',
        support: 'supported',
        meaning: ['Performed $pageview where current URL contains /pricing', 'AND did not perform $exception'],
        categoryIds: ['events', 'event_properties', 'person_properties'],
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: EntityTypes.EVENTS,
                            id: '$pageview',
                            name: '$pageview',
                            properties: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$current_url',
                                    operator: PropertyOperator.IContains,
                                    value: '/pricing',
                                },
                            ],
                        },
                        { type: EntityTypes.EVENTS, id: '$exception', name: '$exception', negation: true },
                    ],
                },
            ],
        },
    },
    {
        id: 'stacked-mixed',
        matchCount: '≈ 1,240 persons',
        surface: 'Insights, replay',
        title: 'Filters, a group and an event together',
        support: 'supported',
        meaning: [
            'Browser is Safari',
            'AND (cohort Power users OR country is FR OR country is GB)',
            'AND performed $pageview where current URL contains /pricing',
        ],
        categoryIds: ['events', 'event_properties', 'person_properties', 'cohorts'],
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Safari'],
                        },
                    ],
                },
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 1 },
                        {
                            type: PropertyFilterType.Event,
                            key: '$geoip_country_code',
                            operator: PropertyOperator.Exact,
                            value: ['FR'],
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$geoip_country_code',
                            operator: PropertyOperator.Exact,
                            value: ['GB'],
                        },
                    ],
                },
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: EntityTypes.EVENTS,
                            id: '$pageview',
                            name: '$pageview',
                            properties: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$current_url',
                                    operator: PropertyOperator.IContains,
                                    value: '/pricing',
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    },
    {
        id: 'contradiction',
        surface: 'Insights',
        title: 'Two values one property cannot hold at once',
        support: 'supported',
        meaning: ['Browser is Safari', 'AND browser is Chrome', 'AND OS is iOS', 'AND OS is set'],
        filters: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Safari'] },
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
            { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.Exact, value: ['iOS'] },
            { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsSet, value: null },
        ],
    },
    {
        id: 'regex-value',
        surface: 'Any property',
        title: 'Regex needs its own editor',
        support: 'needs-design',
        meaning: ['Country code matches regex ^(FR|DE)$'],
        gap: 'The value menu offers seen values as checkboxes, which makes no sense for a pattern. Open a dedicated popover instead: a monospace pattern field, a validity message, and a preview of the seen values that match.',
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$geoip_country_code',
                operator: PropertyOperator.Regex,
                value: '^(FR|DE)$',
            },
        ],
    },
    {
        id: 'text-match-value',
        surface: 'Any property',
        title: 'Contains, starts with and ends with are free text',
        support: 'needs-design',
        meaning: ['Current URL contains /pricing', 'AND current URL does not end with /admin'],
        gap: 'These operators take typed text, but the menu leads with exact seen values as checkboxes. The typed text should come first, and seen values should only suggest text. A multi-value list also collapses to one value on these operators.',
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: '/pricing',
            },
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.NotEndsWith,
                value: '/admin',
            },
        ],
    },
    {
        id: 'number-advanced',
        surface: 'Any numeric property',
        title: 'Numbers could open an advanced editor',
        support: 'needs-design',
        meaning: ['Browser version is greater than 120'],
        gap: 'The value menu says "Type a number" even when the filter already has one, and it has nowhere to adjust it. Add an "Advanced" row that opens a number field with the current value, and a slider when the seen values give a range.',
        filters: [
            {
                type: PropertyFilterType.Event,
                key: '$browser_version',
                operator: PropertyOperator.GreaterThan,
                value: 120,
            },
        ],
    },
    {
        id: 'duration-units',
        surface: 'Web analytics, replay, session properties',
        title: 'Durations need units',
        support: 'needs-design',
        meaning: ['Session duration is greater than 1 hour (stored as 3600 seconds)'],
        gap: 'The chip shows 3600 and the menu expects seconds, without saying so. The chip should read 1h, and the advanced editor should offer seconds, minutes and hours.',
        filters: [
            {
                type: PropertyFilterType.Session,
                key: '$session_duration',
                operator: PropertyOperator.GreaterThan,
                value: 3600,
            },
        ],
    },
]

function ScenarioRow({ scenario }: { scenario: Scenario }): JSX.Element {
    const [filters, setFilters] = useState(scenario.filters ?? [])
    const [filterGroup, setFilterGroup] = useState(scenario.filterGroup)
    const [severity, setSeverity] = useState<string | null>(null)
    const [interval, setInterval] = useState<IntervalType | null>('week')
    const [dates, setDates] = useState<[string | null, string | null]>(['-30d', null])
    const badge = SUPPORT_BADGE[scenario.support]

    return (
        <section
            className="flex flex-col gap-2 border-b border-border py-4"
            data-attr={`filter-bar-scenario-${scenario.id}`}
        >
            <div className="flex flex-wrap items-center gap-2">
                <Badge variant={badge.variant}>{badge.label}</Badge>
                <span className="font-semibold">{scenario.title}</span>
                <span className="text-muted-foreground">{scenario.surface}</span>
            </div>
            <ul className="list-disc ps-5 text-muted-foreground">
                {scenario.meaning.map((line) => (
                    <li key={line}>{line}</li>
                ))}
            </ul>
            {scenario.gap && <p className="m-0">{scenario.gap}</p>}
            <FilterBar
                pageKey={`scenario-${scenario.id}`}
                stackedFooter={scenario.matchCount}
                categoryIds={scenario.categoryIds}
                {...(filterGroup
                    ? { filterGroup, onFilterGroupChange: setFilterGroup }
                    : { filters, onChange: setFilters })}
            >
                {scenario.withSeverityControl && (
                    <FilterBarOptionControl
                        id="severity"
                        label="Severity"
                        icon={IconWarning}
                        value={severity}
                        options={[
                            { value: 'error', label: 'Error' },
                            { value: 'warn', label: 'Warning' },
                            { value: 'info', label: 'Info' },
                        ]}
                        onChange={setSeverity}
                        data-attr="filter-bar-scenario-severity"
                    />
                )}
                {scenario.withControls && (
                    <>
                        <FilterBarDateRange
                            dateFrom={dates[0]}
                            dateTo={dates[1]}
                            onChange={(dateFrom, dateTo) => setDates([dateFrom, dateTo])}
                        />
                        <FilterBarInterval value={interval} onChange={setInterval} />
                    </>
                )}
            </FilterBar>
        </section>
    )
}

function ScenarioList({ support }: { support?: Support }): JSX.Element {
    return (
        <div data-quill className="flex flex-col px-4 text-sm">
            {SCENARIOS.filter((scenario) => !support || scenario.support === support).map((scenario) => (
                <ScenarioRow key={scenario.id} scenario={scenario} />
            ))}
        </div>
    )
}

type StoryArgs = { support?: Support }

const meta: Meta<StoryArgs> = {
    title: 'Filters/FilterBar/Scenarios',
    parameters: {
        layout: 'fullscreen',
        mockDate: '2025-10-10T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [] },
    },
    render: (args) => <ScenarioList {...args} />,
    decorators: [filterBarStoryDecorator],
}
export default meta

type Story = StoryObj<StoryArgs>

function StackedEditorOpen(): JSX.Element {
    const scenario = SCENARIOS.find((candidate) => candidate.id === 'stacked-mixed') as Scenario
    useOnMountEffect(() => {
        filterBarLogic.findMounted({ pageKey: `scenario-${scenario.id}` })?.actions.setStackedOpen(true)
    })
    return (
        <div data-quill className="h-[36rem] px-4 text-sm">
            <ScenarioRow scenario={scenario} />
        </div>
    )
}

export const AllScenarios: Story = { args: {} }

export const Supported: Story = { args: { support: 'supported' } }

export const Lossy: Story = { args: { support: 'lossy' } }

export const ReadOnly: Story = { args: { support: 'unsupported' } }

export const StackedEditor: Story = { render: () => <StackedEditorOpen /> }

export const NeedsDesign: Story = { args: { support: 'needs-design' } }

import { MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { delay } from 'msw'
import { useEffect } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { actionsModel } from '~/models/actionsModel'
import { type AnyPropertyFilter, AvailableFeature, EntityTypes, PropertyFilterType, PropertyOperator } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'
import { recentTaxonomicFiltersLogic } from './recentTaxonomicFiltersLogic'
import { TaxonomicFilter } from './TaxonomicFilter'
import { taxonomicFilterCategoryLayoutLogic } from './taxonomicFilterCategoryLayoutLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { TaxonomicFilterProps } from './types'

const meta: Meta<TaxonomicFilterProps> = {
    title: 'Filters/Taxonomic Filter',
    component: TaxonomicFilter,
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        testOptions: { waitForSelector: '.definition-popover' },
        docs: {
            description: {
                component:
                    'Taxonomic Filter allows users to select from various categories of data in PostHog, like events, actions, properties, etc.',
            },
        },
    },
    tags: ['autodocs'],
}
type Story = StoryObj<TaxonomicFilterProps>
export default meta

export const DashboardPropertySearch: Story = {
    args: {
        taxonomicFilterLogicKey: 'dashboard-property-search',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            TaxonomicFilterGroupType.EventMetadata,
            TaxonomicFilterGroupType.PageviewUrls,
            TaxonomicFilterGroupType.Screens,
            TaxonomicFilterGroupType.EmailAddresses,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.Elements,
            TaxonomicFilterGroupType.SessionProperties,
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ],
        enableKeywordShortcuts: true,
        collapseUrlsToContainsRow: true,
    },
    parameters: { testOptions: { waitForSelector: '.taxonomic-infinite-list' } },
}

function EventsStoryRender(args: TaxonomicFilterProps): JSX.Element {
    useMountedLogic(actionsModel)
    const { setActiveTab } = useActions(
        taxonomicFilterLogic({ ...args, taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string })
    )

    const { setIndex } = useActions(
        infiniteListLogic({
            ...args,
            taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
            listGroupType: TaxonomicFilterGroupType.Events,
        })
    )

    // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
    // - we do want to show the definition popover here too
    useDelayedOnMountEffect(() => {
        setActiveTab(TaxonomicFilterGroupType.Events)
        setIndex(1)
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}

export const EventsFree: Story = {
    render: EventsStoryRender,
    args: {
        taxonomicFilterLogicKey: 'events-free',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    },
    parameters: {
        docs: {
            description: {
                story: 'Basic TaxonomicFilter with Events and Actions tabs in the free version of PostHog.',
            },
        },
    },
}

export const EventsPremium: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])
        const { setActiveTab } = useActions(
            taxonomicFilterLogic({ ...args, taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string })
        )

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        useDelayedOnMountEffect(() => {
            setActiveTab(TaxonomicFilterGroupType.Events)
            setIndex(1)
        })

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'events-premium',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    },
    parameters: {
        docs: {
            description: {
                story: 'TaxonomicFilter with Events and Actions tabs in the premium version of PostHog with INGESTION_TAXONOMY feature enabled.',
            },
        },
    },
}

export const Actions: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Actions,
            })
        )

        // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
        // - we do want to show the definition popover here too
        useDelayedOnMountEffect(() => setIndex(0))

        return (
            <div className="w-fit border rounded p-2">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'actions',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Actions],
    },
    parameters: {
        docs: {
            description: {
                story: 'TaxonomicFilter showing only Actions tab.',
            },
        },
    },
}

export const Properties: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'properties',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
    },
    parameters: {
        docs: {
            description: {
                story: 'TaxonomicFilter showing Event Properties and Person Properties tabs.',
            },
        },
    },
}

export const SlowExpansionCount: Story = {
    render: Properties.render,
    args: {
        taxonomicFilterLogicKey: 'slow-expansion-count',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
        eventNames: ['page_opened'],
        initialSearchQuery: 'name',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/property_definitions': async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const scoped = params.has('filter_by_event_names')
                    const results = [{ id: 'page_name', name: 'page_name' }].filter((item) =>
                        item.name.includes(params.get('search') ?? '')
                    )
                    await delay(scoped ? 100 : 8000)
                    return { results, count: scoped ? results.length : 9 }
                },
            },
        }),
    ],
    parameters: {
        testOptions: { waitForSelector: '[data-attr="prop-filter-event_properties-0"]' },
        docs: {
            description: {
                story: 'Scoped results appear while the full count is still loading. The expansion option arrives below them after eight seconds.',
            },
        },
    },
}

export const NumericalProperties: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'properties',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
        showNumericalPropsOnly: true,
    },
    parameters: {
        docs: {
            description: {
                story: 'TaxonomicFilter showing numerical properties only includes a small icon to indicate.',
            },
        },
    },
}

export const ThreeGroupsDefaultLayout: Story = {
    render: EventsStoryRender,
    args: {
        taxonomicFilterLogicKey: 'three-groups-default-layout',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
        ],
    },
}

export const SixGroupsDefaultLayout: Story = {
    render: EventsStoryRender,
    args: {
        taxonomicFilterLogicKey: 'six-groups-default-layout',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.Elements,
        ],
    },
}

function propertyFilter(filter: AnyPropertyFilter): AnyPropertyFilter {
    return filter
}

const RECENT_ITEMS = [
    {
        groupType: TaxonomicFilterGroupType.EventProperties,
        groupName: 'Event properties',
        value: '$browser',
        item: { name: '$browser' },
        propertyFilter: propertyFilter({
            type: PropertyFilterType.Event,
            key: '$browser',
            operator: PropertyOperator.Exact,
            value: 'Chrome',
        }),
    },
    {
        groupType: TaxonomicFilterGroupType.Events,
        groupName: 'Events',
        value: 'signed up',
        item: { name: 'signed up', id: 'a' },
    },
    {
        groupType: TaxonomicFilterGroupType.EventProperties,
        groupName: 'Event properties',
        value: '$os',
        item: { name: '$os' },
        propertyFilter: propertyFilter({
            type: PropertyFilterType.Event,
            key: '$os',
            operator: PropertyOperator.Exact,
            value: 'Mac OS X',
        }),
    },
    {
        groupType: TaxonomicFilterGroupType.Events,
        groupName: 'Events',
        value: 'viewed insights',
        item: { name: 'viewed insights', id: 'b' },
    },
    {
        groupType: TaxonomicFilterGroupType.EventProperties,
        groupName: 'Event properties',
        value: '$current_url',
        item: { name: '$current_url' },
        propertyFilter: propertyFilter({
            type: PropertyFilterType.Event,
            key: '$current_url',
            operator: PropertyOperator.IContains,
            value: 'https://app.example.com/organizations/very-long-org-name/projects/some-project-id/dashboards/analytics-overview?date_from=2025-01-01&date_to=2025-12-31&interval=month',
        }),
    },
]

function SeedRecents({ count }: { count: number }): null {
    useMountedLogic(recentTaxonomicFiltersLogic)

    useOnMountEffect(() => {
        recentTaxonomicFiltersLogic.actions.clearRecentFilters()
        for (const recent of RECENT_ITEMS.slice(0, count)) {
            recentTaxonomicFiltersLogic.actions.recordRecentFilter({
                groupType: recent.groupType,
                groupName: recent.groupName,
                value: recent.value,
                item: recent.item,
                teamId: MOCK_TEAM_ID,
                propertyFilter: recent.propertyFilter,
            })
        }
    })

    return null
}

const SUGGESTED_FILTERS_ARGS = {
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.SuggestedFilters,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Events,
    ],
}

const SUGGESTED_FILTERS_PARAMETERS = {
    testOptions: { waitForSelector: '.taxonomic-infinite-list' },
}

export const SuggestedFiltersNoRecents: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={0} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...SUGGESTED_FILTERS_ARGS,
        taxonomicFilterLogicKey: 'suggested-no-recents',
    },
    parameters: SUGGESTED_FILTERS_PARAMETERS,
}

export const SuggestedFiltersOneRecent: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={1} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...SUGGESTED_FILTERS_ARGS,
        taxonomicFilterLogicKey: 'suggested-one-recent',
    },
    parameters: SUGGESTED_FILTERS_PARAMETERS,
}

export const SuggestedFiltersFourRecents: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={4} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...SUGGESTED_FILTERS_ARGS,
        taxonomicFilterLogicKey: 'suggested-four-recents',
    },
    parameters: SUGGESTED_FILTERS_PARAMETERS,
}

export const SuggestedFiltersFiveRecentsWithTruncation: Story = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={5} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...SUGGESTED_FILTERS_ARGS,
        taxonomicFilterLogicKey: 'suggested-five-recents-truncation',
    },
    parameters: SUGGESTED_FILTERS_PARAMETERS,
}

/**
 * This story demonstrates that PageviewUrls, Screens, and EmailAddresses are promoted
 * to the top of the group list (after SuggestedFilters and RecentFilters) regardless of
 * where they appear in the original taxonomicGroupTypes array.
 */
export const PromotedGroupsAreReordered: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        const logicKey = args.taxonomicFilterLogicKey as string
        const { setSearchQuery } = useActions(taxonomicFilterLogic({ ...args, taxonomicFilterLogicKey: logicKey }))

        // Type a search query so all groups (including those with minSearchQueryLength) load
        // and their Spinners resolve, making the snapshot stable.
        useOnMountEffect(() => setSearchQuery('check the order of the groups as presented'))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={3} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'promoted-groups-reordered',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.PageviewUrls,
            TaxonomicFilterGroupType.Screens,
            TaxonomicFilterGroupType.EmailAddresses,
        ],
    },
    parameters: {
        ...SUGGESTED_FILTERS_PARAMETERS,
        docs: {
            description: {
                story: 'PageviewUrls, Screens, and EmailAddresses are defined at the end of the group list but get promoted to the top positions, right after Suggested filters and Recents.',
            },
        },
    },
}

export const AutocaptureContextPromotesElements: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={2} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'autocapture-promotes-elements',
        eventNames: ['$autocapture'],
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Elements,
        ],
    },
    parameters: {
        ...SUGGESTED_FILTERS_PARAMETERS,
        docs: {
            description: {
                story: 'When $autocapture is the selected event, SuggestedFilters shows "text" and "selector" autocapture properties and the Elements group is promoted after SuggestedFilters/Recents.',
            },
        },
    },
}

export const MCPToolCallContextLeadsWithMCPProperties: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <SeedRecents count={0} />
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'mcp-tool-call-context',
        eventNames: ['$mcp_tool_call'],
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.MCPProperties,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
        ],
    },
    parameters: {
        ...SUGGESTED_FILTERS_PARAMETERS,
        docs: {
            description: {
                story: 'When the picker is scoped to $mcp_tool_call, the known @posthog/mcp schema is separated into a leading "MCP properties" group, and SuggestedFilters leads with the tool name (the event\'s primary property) and error state. Without an $mcp_* event in scope the group disappears entirely.',
            },
        },
    },
}

function CategoryDropdownStoryRender(args: TaxonomicFilterProps): JSX.Element {
    useMountedLogic(actionsModel)

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}

const CATEGORY_DROPDOWN_ARGS: TaxonomicFilterProps = {
    taxonomicFilterLogicKey: 'category-dropdown',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.PersonProperties,
    ],
}

const CATEGORY_DROPDOWN_PARAMETERS = {
    testOptions: { waitForSelector: '.taxonomic-infinite-list' },
}

export const CategoryDropdown: Story = {
    render: CategoryDropdownStoryRender,
    args: CATEGORY_DROPDOWN_ARGS,
    parameters: {
        ...CATEGORY_DROPDOWN_PARAMETERS,
        docs: {
            description: {
                story: 'The active category appears as a pill in the search input. Open it to browse categories or dock the category rail.',
            },
        },
    },
}

export const CategoryRailPinned: Story = {
    render: CategoryRailStoryRender,
    args: CATEGORY_DROPDOWN_ARGS,
    parameters: {
        testOptions: { waitForSelector: '[data-attr="taxonomic-category-rail-unpin"]' },
        docs: {
            description: {
                story: 'Pinned categories remain visible beside the results on wide layouts.',
            },
        },
    },
}

function CategoryRailStoryRender(args: TaxonomicFilterProps): JSX.Element {
    useMountedLogic(actionsModel)
    const { setCategoryRailPinned } = useActions(taxonomicFilterCategoryLayoutLogic)

    useEffect(() => {
        setCategoryRailPinned(true)
        return () => {
            setCategoryRailPinned(false)
        }
    }, [setCategoryRailPinned])

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}

// The committed selection of a renamed series ('signed up', renamed "Completed sign-up")
// is promoted to the top of the list, labelled with the rename and revealing the
// underlying event as secondary text (tooltip on hover).
const RENAMED_SERIES_ARGS: TaxonomicFilterProps = {
    groupType: TaxonomicFilterGroupType.Events,
    value: 'signed up',
    filter: {
        type: EntityTypes.EVENTS,
        id: 'signed up',
        name: 'signed up',
        custom_name: 'Completed sign-up',
        order: 0,
    },
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}

const RENAMED_SERIES_PARAMETERS = {
    // Wait on the promoted renamed row itself: the picker also mounts hidden, empty
    // Recent/Pinned lists ahead of the active Events list, and the test runner waits on
    // the FIRST `.taxonomic-infinite-list` match — which never becomes visible.
    testOptions: { waitForSelector: '.taxonomic-list-row .EntityFilterInfo' },
}

export const RenamedSeriesSelected: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...RENAMED_SERIES_ARGS,
        taxonomicFilterLogicKey: 'renamed-series-selected',
    },
    parameters: {
        ...RENAMED_SERIES_PARAMETERS,
        docs: {
            description: {
                story: 'Reopening the picker on a renamed series: the committed selection leads the Events list, labelled "Completed sign-up" with the underlying `signed up` event shown alongside (and in a tooltip on hover), so the row connects to the series the user clicked.',
            },
        },
    },
}

export const RenamedSeriesSelectedWithAllResults: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        ...RENAMED_SERIES_ARGS,
        taxonomicFilterLogicKey: 'renamed-series-selected-all',
    },
    parameters: {
        ...RENAMED_SERIES_PARAMETERS,
        docs: {
            description: {
                story: 'Same renamed-series selection with All results. The promoted committed row still shows the rename with the underlying event.',
            },
        },
    },
}

export const FailedFetchOffersRetry: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        const { setSearchQuery } = useActions(
            taxonomicFilterLogic({ ...args, taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string })
        )

        useOnMountEffect(() => setSearchQuery('user_signed_up'))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'events-failed-fetch',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions': () => [500, { detail: 'server error' }],
            },
        }),
    ],
    parameters: {
        testOptions: { waitForSelector: '[data-attr="taxonomic-retry-remote-items"]' },
        docs: {
            description: {
                story: 'When the search request fails, the list says so and offers a retry, rather than showing the same "No results" as a genuine empty search.',
            },
        },
    },
}

export const CohortsWithRealtimeStates: Story = {
    args: {
        taxonomicFilterLogicKey: 'cohorts-realtime',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Cohorts],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/cohorts/': [
                    {
                        id: 1,
                        name: 'Viewed pricing this week',
                        count: 4321,
                        is_static: false,
                        realtime: { state: 'ready', ready_at: '2023-07-03T09:40:00Z', build: null },
                    },
                    {
                        id: 2,
                        name: 'Completed onboarding',
                        count: 210,
                        is_static: false,
                        realtime: {
                            state: 'building',
                            ready_at: null,
                            build: { phase: 'scanning', percent_complete: 45, updated_at: '2023-07-03T23:58:00Z' },
                        },
                    },
                    {
                        id: 3,
                        name: 'Churn risk',
                        count: 76,
                        is_static: false,
                        realtime: { state: 'needs_attention', ready_at: null, build: null },
                    },
                    { id: 4, name: 'Beta testers', count: 89, is_static: true, realtime: null },
                    { id: 5, name: 'Signed up last month', count: 1200, is_static: false, realtime: null },
                ],
            },
        }),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING],
        // The preparing cohort's tag holds a spinner while its build runs, so the runner cannot
        // wait for every loader to disappear here.
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="cohort-realtime-tag"]' },
        docs: {
            description: {
                story: 'Cohort rows carry their realtime trait, so someone picking one for a feature flag sees which cohorts flags can already target and which are still being prepared.',
            },
        },
    },
}

export const EmptyEventsWithStaleToggle: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)
        const { setSearchQuery } = useActions(
            taxonomicFilterLogic({ ...args, taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string })
        )

        useOnMountEffect(() => setSearchQuery('my_ancient_event'))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'events-stale-toggle',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions': [],
            },
        }),
    ],
    parameters: {
        testOptions: { waitForSelector: '[data-attr="taxonomic-include-stale-events"]' },
        docs: {
            description: {
                story: 'When a search on the Events tab returns no results (all matches are stale), an "Include stale events" button appears so users can opt in to seeing events older than 30 days.',
            },
        },
    },
}

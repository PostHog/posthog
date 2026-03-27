import { MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { useAvailableFeatures } from '~/mocks/features'
import { actionsModel } from '~/models/actionsModel'
import { type AnyPropertyFilter, AvailableFeature, PropertyFilterType, PropertyOperator } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'
import { recentTaxonomicFiltersLogic } from './recentTaxonomicFiltersLogic'
import { TaxonomicFilter } from './TaxonomicFilter'
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
                    'Taxonomic Filter allows users to select from various categories of data in PostHog, like events, actions, properties, etc. It supports both horizontal and vertical (columnar) layouts.',
            },
        },
    },
    tags: ['autodocs'],
}
type Story = StoryObj<TaxonomicFilterProps>
export default meta

export const EventsFree: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
        // - we do want to show the definition popover here too
        useDelayedOnMountEffect(() => setIndex(1))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
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

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        useDelayedOnMountEffect(() => setIndex(1))

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

/**
 * This story demonstrates the automatic columnar layout that's triggered when there are more than 4 group types.
 * The layout switches from horizontal tabs to a vertical/columnar layout to better organize the many categories.
 */
export const Columnar: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        useDelayedOnMountEffect(() => setIndex(1))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'columnar-five-groups',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Cohorts,
        ],
    },
    parameters: {
        docs: {
            description: {
                story: 'Automatically switches to columnar/vertical layout when there are 5 or more group types.',
            },
        },
    },
}

/**
 * This story demonstrates forcing the columnar/vertical layout even when there are fewer than 5 group types.
 * This is done by setting the `useVerticalLayout` prop to true.
 */
export const ForceColumnar: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        useDelayedOnMountEffect(() => setIndex(1))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'force-columnar-three-groups',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
        ],
        useVerticalLayout: true,
    },
    parameters: {
        docs: {
            description: {
                story: 'Forces columnar/vertical layout even with only 3 group types by setting useVerticalLayout to true.',
            },
        },
    },
}

/**
 * This story demonstrates forcing a horizontal layout even when there are many group types.
 * This is done by setting the `useVerticalLayout` prop to false.
 */
export const ForceNonColumnar: Story = {
    render: (args) => {
        useMountedLogic(actionsModel)

        const { setIndex } = useActions(
            infiniteListLogic({
                ...args,
                taxonomicFilterLogicKey: args.taxonomicFilterLogicKey as string,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
        )

        useDelayedOnMountEffect(() => setIndex(1))

        return (
            <div className="w-fit border rounded p-2 bg-surface-primary">
                <TaxonomicFilter {...args} />
            </div>
        )
    },
    args: {
        taxonomicFilterLogicKey: 'force-non-columnar-six-groups',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.Elements,
        ],
        useVerticalLayout: false,
    },
    parameters: {
        docs: {
            description: {
                story: 'Forces horizontal layout even with 6 group types by setting useVerticalLayout to false.',
            },
        },
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
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                recent.groupType,
                recent.groupName,
                recent.value,
                recent.item,
                MOCK_TEAM_ID,
                recent.propertyFilter
            )
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
    featureFlags: [FEATURE_FLAGS.TAXONOMIC_FILTER_RECENTS],
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

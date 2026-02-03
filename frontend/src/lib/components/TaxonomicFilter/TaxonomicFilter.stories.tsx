import { Meta, StoryFn } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { useAvailableFeatures } from '~/mocks/features'
import { actionsModel } from '~/models/actionsModel'
import { AvailableFeature } from '~/types'

import { TaxonomicFilter } from './TaxonomicFilter'
import { infiniteListLogic } from './infiniteListLogic'
import { recentItemsLogic } from './recentItemsLogic'

const meta: Meta<typeof TaxonomicFilter> = {
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
export default meta

export const EventsFree: StoryFn<typeof TaxonomicFilter> = (args) => {
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
}
EventsFree.args = {
    taxonomicFilterLogicKey: 'events-free',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}
EventsFree.parameters = {
    docs: {
        description: {
            story: 'Basic TaxonomicFilter with Events and Actions tabs in the free version of PostHog.',
        },
    },
}

export const EventsPremium: StoryFn<typeof TaxonomicFilter> = (args) => {
    useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])
    return <EventsFree {...args} />
}
EventsPremium.args = {
    taxonomicFilterLogicKey: 'events-premium',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}
EventsPremium.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter with Events and Actions tabs in the premium version of PostHog with INGESTION_TAXONOMY feature enabled.',
        },
    },
}

export const Actions: StoryFn<typeof TaxonomicFilter> = (args) => {
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
}
Actions.args = {
    taxonomicFilterLogicKey: 'actions',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Actions],
}
Actions.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter showing only Actions tab.',
        },
    },
}

export const Properties: StoryFn<typeof TaxonomicFilter> = (args) => {
    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
Properties.args = {
    taxonomicFilterLogicKey: 'properties',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
}
Properties.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter showing Event Properties and Person Properties tabs.',
        },
    },
}

export const NumericalProperties: StoryFn<typeof TaxonomicFilter> = (args) => {
    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
NumericalProperties.args = {
    taxonomicFilterLogicKey: 'properties',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
    showNumericalPropsOnly: true,
}
NumericalProperties.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter showing numerical properties only includes a small icon to indicate.',
        },
    },
}

/**
 * This story demonstrates the automatic columnar layout that's triggered when there are more than 4 group types.
 * The layout switches from horizontal tabs to a vertical/columnar layout to better organize the many categories.
 */
export const Columnar: StoryFn<typeof TaxonomicFilter> = (args) => {
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
}
Columnar.args = {
    taxonomicFilterLogicKey: 'columnar-five-groups',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.Cohorts,
    ],
}
Columnar.parameters = {
    docs: {
        description: {
            story: 'Automatically switches to columnar/vertical layout when there are 5 or more group types.',
        },
    },
}

/**
 * This story demonstrates forcing the columnar/vertical layout even when there are fewer than 5 group types.
 * This is done by setting the `useVerticalLayout` prop to true.
 */
export const ForceColumnar: StoryFn<typeof TaxonomicFilter> = (args) => {
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
}
ForceColumnar.args = {
    taxonomicFilterLogicKey: 'force-columnar-three-groups',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.EventProperties,
    ],
    useVerticalLayout: true,
}
ForceColumnar.parameters = {
    docs: {
        description: {
            story: 'Forces columnar/vertical layout even with only 3 group types by setting useVerticalLayout to true.',
        },
    },
}

/**
 * This story demonstrates forcing a horizontal layout even when there are many group types.
 * This is done by setting the `useVerticalLayout` prop to false.
 */
export const ForceNonColumnar: StoryFn<typeof TaxonomicFilter> = (args) => {
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
}
ForceNonColumnar.args = {
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
}
ForceNonColumnar.parameters = {
    docs: {
        description: {
            story: 'Forces horizontal layout even with 6 group types by setting useVerticalLayout to false.',
        },
    },
}

/**
 * This story demonstrates the RecentEvents tab in event picker mode with some recent events.
 */
export const RecentEventsWithItems: StoryFn<typeof TaxonomicFilter> = (args) => {
    const logic = useMountedLogic(recentItemsLogic)
    useMountedLogic(actionsModel)

    useDelayedOnMountEffect(() => {
        // Clear and add some recent events
        logic.actions.clearRecentEvents()
        logic.actions.addRecentEvent({
            type: TaxonomicFilterGroupType.Events,
            value: '$pageview',
            name: '$pageview',
            timestamp: Date.now() - 10000,
        })
        logic.actions.addRecentEvent({
            type: TaxonomicFilterGroupType.Events,
            value: '$autocapture',
            name: '$autocapture',
            timestamp: Date.now() - 5000,
        })
        logic.actions.addRecentEvent({
            type: TaxonomicFilterGroupType.Events,
            value: 'user_signed_up',
            name: 'user_signed_up',
            timestamp: Date.now(),
        })
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
RecentEventsWithItems.args = {
    taxonomicFilterLogicKey: 'recent-events-with-items',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.RecentEvents,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
    ],
}
RecentEventsWithItems.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter in event picker mode showing the Recent events tab with previously selected events.',
        },
    },
}

/**
 * This story demonstrates the RecentEvents tab in event picker mode with no recent events.
 */
export const RecentEventsEmpty: StoryFn<typeof TaxonomicFilter> = (args) => {
    const logic = useMountedLogic(recentItemsLogic)
    useMountedLogic(actionsModel)

    useDelayedOnMountEffect(() => {
        logic.actions.clearRecentEvents()
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
RecentEventsEmpty.args = {
    taxonomicFilterLogicKey: 'recent-events-empty',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.RecentEvents,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
    ],
}
RecentEventsEmpty.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter in event picker mode showing the Recent events tab with no recent events.',
        },
    },
}

/**
 * This story demonstrates the RecentProperties tab in property picker mode with some recent properties.
 */
export const RecentPropertiesWithItems: StoryFn<typeof TaxonomicFilter> = (args) => {
    const logic = useMountedLogic(recentItemsLogic)

    useDelayedOnMountEffect(() => {
        // Clear and add some recent properties
        logic.actions.clearRecentProperties()
        logic.actions.addRecentProperty({
            type: TaxonomicFilterGroupType.EventProperties,
            value: '$browser',
            name: '$browser',
            timestamp: Date.now() - 10000,
        })
        logic.actions.addRecentProperty({
            type: TaxonomicFilterGroupType.PersonProperties,
            value: 'email',
            name: 'email',
            timestamp: Date.now() - 5000,
        })
        logic.actions.addRecentProperty({
            type: TaxonomicFilterGroupType.EventProperties,
            value: '$current_url',
            name: '$current_url',
            timestamp: Date.now(),
        })
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
RecentPropertiesWithItems.args = {
    taxonomicFilterLogicKey: 'recent-properties-with-items',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.RecentProperties,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
    ],
}
RecentPropertiesWithItems.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter in property picker mode showing the Recent properties tab with previously selected properties.',
        },
    },
}

/**
 * This story demonstrates the RecentProperties tab in property picker mode with no recent properties.
 */
export const RecentPropertiesEmpty: StoryFn<typeof TaxonomicFilter> = (args) => {
    const logic = useMountedLogic(recentItemsLogic)

    useDelayedOnMountEffect(() => {
        logic.actions.clearRecentProperties()
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
RecentPropertiesEmpty.args = {
    taxonomicFilterLogicKey: 'recent-properties-empty',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.RecentProperties,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
    ],
}
RecentPropertiesEmpty.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter in property picker mode showing the Recent properties tab with no recent properties.',
        },
    },
}

/**
 * This story demonstrates recent tabs with the columnar layout.
 */
export const RecentEventsColumnar: StoryFn<typeof TaxonomicFilter> = (args) => {
    const logic = useMountedLogic(recentItemsLogic)
    useMountedLogic(actionsModel)

    useDelayedOnMountEffect(() => {
        logic.actions.clearRecentEvents()
        logic.actions.addRecentEvent({
            type: TaxonomicFilterGroupType.Events,
            value: '$pageview',
            name: '$pageview',
            timestamp: Date.now(),
        })
        logic.actions.addRecentEvent({
            type: TaxonomicFilterGroupType.Events,
            value: '$autocapture',
            name: '$autocapture',
            timestamp: Date.now() + 100,
        })
    })

    return (
        <div className="w-fit border rounded p-2 bg-surface-primary">
            <TaxonomicFilter {...args} />
        </div>
    )
}
RecentEventsColumnar.args = {
    taxonomicFilterLogicKey: 'recent-events-columnar',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.RecentEvents,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
    ],
}
RecentEventsColumnar.parameters = {
    docs: {
        description: {
            story: 'TaxonomicFilter with Recent events tab in columnar layout (5+ groups).',
        },
    },
}

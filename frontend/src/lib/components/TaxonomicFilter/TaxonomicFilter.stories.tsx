import { Meta, StoryFn } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect } from 'react'

import { useAvailableFeatures } from '~/mocks/features'
import { actionsModel } from '~/models/actionsModel'
import { AvailableFeature } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'
import { TaxonomicFilter } from './TaxonomicFilter'

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
    useEffect(() => {
        // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
        // - we do want to show the definition popover here too
        setIndex(1)
    }, [setIndex])
    return (
        <div className="w-fit border rounded p-2 bg-card">
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
    useEffect(() => {
        // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
        // - we do want to show the definition popover here too
        setIndex(0)
    }, [setIndex])
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
        <div className="w-fit border rounded p-2 bg-card">
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
    useEffect(() => {
        setIndex(1)
    }, [setIndex])
    return (
        <div className="w-fit border rounded p-2 bg-card">
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
    useEffect(() => {
        setIndex(1)
    }, [setIndex])
    return (
        <div className="w-fit border rounded p-2 bg-card">
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
    useEffect(() => {
        setIndex(1)
    }, [setIndex])
    return (
        <div className="w-fit border rounded p-2 bg-card">
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

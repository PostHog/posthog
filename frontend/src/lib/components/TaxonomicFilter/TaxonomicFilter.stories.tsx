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
    },
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
    }, [])
    return (
        <div className="w-fit border rounded p-2 bg-bg-light">
            <TaxonomicFilter {...args} />
        </div>
    )
}
EventsFree.args = {
    taxonomicFilterLogicKey: 'events-free',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}

export const EventsPremium: StoryFn<typeof TaxonomicFilter> = (args) => {
    useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])
    return <EventsFree {...args} />
}
EventsPremium.args = {
    taxonomicFilterLogicKey: 'events-premium',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
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
    }, [])
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

export const Properties: StoryFn<typeof TaxonomicFilter> = (args) => {
    return (
        <div className="w-fit border rounded p-2 bg-bg-light">
            <TaxonomicFilter {...args} />
        </div>
    )
}
Properties.args = {
    taxonomicFilterLogicKey: 'properties',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
}

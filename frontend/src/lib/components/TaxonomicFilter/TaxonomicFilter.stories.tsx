import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useActions, useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { useEffect } from 'react'
import { infiniteListLogic } from './infiniteListLogic'
import { ComponentMeta, ComponentStoryFn } from '@storybook/react'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

export default {
    title: 'Filters/Taxonomic Filter',
    component: TaxonomicFilter,
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        testOptions: { waitForLoadersToDisappear: '.definition-popover' },
    },
} as ComponentMeta<typeof TaxonomicFilter>

export const EventsFree: ComponentStoryFn<typeof TaxonomicFilter> = (args) => {
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

export const EventsPremium: ComponentStoryFn<typeof TaxonomicFilter> = (args) => {
    useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])
    return <EventsFree {...args} />
}
EventsPremium.args = {
    taxonomicFilterLogicKey: 'events-premium',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}

export const Actions: ComponentStoryFn<typeof TaxonomicFilter> = (args) => {
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
        <div className="w-fit border rounded p-2 bg-white">
            <TaxonomicFilter {...args} />
        </div>
    )
}
Actions.args = {
    taxonomicFilterLogicKey: 'actions',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Actions],
}

export const Properties: ComponentStoryFn<typeof TaxonomicFilter> = (args) => {
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

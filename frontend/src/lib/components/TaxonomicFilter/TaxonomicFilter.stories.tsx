import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useActions, useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { useEffect } from 'react'
import { infiniteListLogic } from './infiniteListLogic'
import { StoryObj, Meta } from '@storybook/react'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

const meta: Meta<typeof TaxonomicFilter> = {
    title: 'Filters/Taxonomic Filter',
    component: TaxonomicFilter,
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        testOptions: { waitForLoadersToDisappear: '.definition-popover' },
    },
}
export default meta

export const EventsFree: StoryObj<typeof TaxonomicFilter> = {
    render: (args) => {
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
    },

    args: {
        taxonomicFilterLogicKey: 'events-free',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    },
}

export const EventsPremium: StoryObj<typeof TaxonomicFilter> = {
    render: (args) => {
        useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])
        return <EventsFree {...args} />
    },

    args: {
        taxonomicFilterLogicKey: 'events-premium',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    },
}

export const Actions: StoryObj<typeof TaxonomicFilter> = {
    render: (args) => {
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
    },

    args: {
        taxonomicFilterLogicKey: 'actions',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Actions],
    },
}

export const Properties: StoryObj<typeof TaxonomicFilter> = {
    render: (args) => {
        return (
            <div className="w-fit border rounded p-2 bg-bg-light">
                <TaxonomicFilter {...args} />
            </div>
        )
    },

    args: {
        taxonomicFilterLogicKey: 'properties',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
    },
}

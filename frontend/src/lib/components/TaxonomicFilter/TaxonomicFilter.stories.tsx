import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { useEffect } from 'react'
import { infiniteListLogic } from './infiniteListLogic'
import { Meta } from '@storybook/react'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

export default {
    title: 'Filters/Taxonomic Filter',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        testOptions: { waitForLoadersToDisappear: '.definition-popover' },
    },
} as Meta

export function EventsFree(): JSX.Element {
    useMountedLogic(actionsModel)
    useEffect(() => {
        // Highlight the second item, as the first one is "All events", which doesn't have a definition to show
        // - we do want to show the definition popover here too
        infiniteListLogic
            .find({ taxonomicFilterLogicKey: 'events-free', listGroupType: TaxonomicFilterGroupType.Events })
            .actions.setIndex(1)
    }, [])

    return (
        <div className="w-fit border rounded p-2 bg-white">
            <TaxonomicFilter
                taxonomicFilterLogicKey="events-free"
                taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            />
        </div>
    )
}

export function EventsPremium(): JSX.Element {
    useAvailableFeatures([AvailableFeature.INGESTION_TAXONOMY])

    return <EventsFree />
}

export function Properties(): JSX.Element {
    return (
        <div className="w-fit border rounded p-2 bg-white">
            <TaxonomicFilter
                taxonomicFilterLogicKey="properties"
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ]}
            />
        </div>
    )
}

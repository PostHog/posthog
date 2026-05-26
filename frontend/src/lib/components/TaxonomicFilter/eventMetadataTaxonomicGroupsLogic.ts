import { connect, kea, key, path, props, selectors } from 'kea'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { getEventMetadataDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { PropertyDefinition } from '~/types'

import type { eventMetadataTaxonomicGroupsLogicType } from './eventMetadataTaxonomicGroupsLogicType'

export const eventMetadataTaxonomicGroupsLogic = kea<eventMetadataTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'eventMetadataTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [propertyDefinitionsModel, ['eventMetadataPropertyDefinitions']],
    })),

    selectors({
        eventMetadataTaxonomicGroups: [
            (s) => [s.eventMetadataPropertyDefinitions],
            (eventMetadataPropertyDefinitions): TaxonomicFilterGroup[] => [
                {
                    name: 'Event metadata',
                    searchPlaceholder: 'event metadata',
                    type: TaxonomicFilterGroupType.EventMetadata,
                    options: eventMetadataPropertyDefinitions,
                    getIcon: (option: PropertyDefinition) => getEventMetadataDefinitionIcon(option),
                    getName: (option: PropertyDefinition) => {
                        const coreDefinition = getCoreFilterDefinition(
                            option.id,
                            TaxonomicFilterGroupType.EventMetadata
                        )
                        return coreDefinition ? coreDefinition.label : option.name
                    },
                    getValue: (option: PropertyDefinition) => option.id,
                    valuesEndpoint: (key) => {
                        return `api/event/values/?key=${encodeURIComponent(key)}&is_column=true`
                    },
                    getPopoverHeader: () => 'Event metadata',
                },
            ],
        ],
    }),
])

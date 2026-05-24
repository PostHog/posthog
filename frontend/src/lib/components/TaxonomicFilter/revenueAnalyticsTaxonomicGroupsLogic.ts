import { connect, kea, key, path, props, selectors } from 'kea'

import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { getRevenueAnalyticsDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { projectLogic } from 'scenes/projectLogic'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { PropertyDefinition, PropertyDefinitionType } from '~/types'

import type { revenueAnalyticsTaxonomicGroupsLogicType } from './revenueAnalyticsTaxonomicGroupsLogicType'

export const revenueAnalyticsTaxonomicGroupsLogic = kea<revenueAnalyticsTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'revenueAnalyticsTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    selectors({
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        revenueAnalyticsTaxonomicGroups: [
            (s) => [s.currentProjectId, s.excludedProperties],
            (projectId, excludedProperties): TaxonomicFilterGroup[] => [
                {
                    name: 'Revenue analytics properties',
                    searchPlaceholder: 'revenue analytics properties',
                    type: TaxonomicFilterGroupType.RevenueAnalyticsProperties,
                    options: Object.entries(
                        CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.RevenueAnalyticsProperties]
                    )
                        .map(([key, { type: property_type }]) => ({
                            id: key,
                            name: key,
                            value: key,
                            property_type,
                            type: PropertyDefinitionType.RevenueAnalytics,
                        }))
                        .filter(
                            (o) =>
                                !excludedProperties[TaxonomicFilterGroupType.RevenueAnalyticsProperties]?.includes(
                                    o.value
                                )
                        ),
                    getIcon: (option: PropertyDefinition): JSX.Element => getRevenueAnalyticsDefinitionIcon(option),
                    getName: (option: PropertyDefinition) => {
                        const coreDefinition = getCoreFilterDefinition(
                            option.id,
                            TaxonomicFilterGroupType.RevenueAnalyticsProperties
                        )

                        return coreDefinition ? coreDefinition.label : option.name
                    },
                    getValue: (option: PropertyDefinition) => option.id,
                    valuesEndpoint: (key) => {
                        return `api/environments/${projectId}/revenue_analytics/taxonomy/values?key=${encodeURIComponent(
                            key
                        )}`
                    },
                    getPopoverHeader: () => 'Revenue analytics properties',
                },
            ],
        ],
    }),
])

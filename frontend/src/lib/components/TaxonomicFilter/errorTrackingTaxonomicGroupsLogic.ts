import { connect, kea, key, path, props, selectors } from 'kea'

import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { getProductEventPropertyFilterOptions } from 'scenes/hog-functions/filters/HogFunctionFiltersInternal'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

import type { errorTrackingTaxonomicGroupsLogicType } from './errorTrackingTaxonomicGroupsLogicType'

export const errorTrackingTaxonomicGroupsLogic = kea<errorTrackingTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'errorTrackingTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId']],
    })),

    selectors({
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        errorTrackingTaxonomicGroups: [
            (s) => [s.currentTeam, s.currentProjectId, s.excludedProperties],
            (currentTeam, projectId, excludedProperties): TaxonomicFilterGroup[] => [
                {
                    name: 'Issues',
                    searchPlaceholder: 'issues',
                    type: TaxonomicFilterGroupType.ErrorTrackingIssues,
                    options: Object.entries(
                        CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.ErrorTrackingIssues]
                    )
                        .map(([key, { label }]) => ({
                            value: key,
                            name: label,
                        }))
                        .filter(
                            (o) => !excludedProperties[TaxonomicFilterGroupType.ErrorTrackingIssues]?.includes(o.value)
                        ),
                    getName: (option) => option.name,
                    getValue: (option) => option.value,
                    valuesEndpoint: (key) => `api/environments/${projectId}/error_tracking/issues/values?key=` + key,
                    getPopoverHeader: () => 'Issues',
                },
                {
                    name: 'Exception properties',
                    searchPlaceholder: 'exceptions',
                    type: TaxonomicFilterGroupType.ErrorTrackingProperties,
                    options: [
                        ...getProductEventPropertyFilterOptions('error-tracking').map((value) => ({
                            name: value,
                            value,
                            group: TaxonomicFilterGroupType.EventProperties,
                        })),
                        ...(currentTeam?.person_display_name_properties
                            ? currentTeam.person_display_name_properties.map((property) => ({
                                  name: property,
                                  value: property,
                                  group: TaxonomicFilterGroupType.PersonProperties,
                              }))
                            : []),
                    ],
                    getIcon: getPropertyDefinitionIcon,
                    getPopoverHeader: () => 'Exception properties',
                },
            ],
        ],
    }),
])

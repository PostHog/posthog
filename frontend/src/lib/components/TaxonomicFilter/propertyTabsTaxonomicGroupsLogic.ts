import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import { propertyTaxonomicGroupProps } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { isString, pluralize } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { PersonProperty, PropertyDefinition } from '~/types'

import type { propertyTabsTaxonomicGroupsLogicType } from './propertyTabsTaxonomicGroupsLogicType'

export const propertyTabsTaxonomicGroupsLogic = kea<propertyTabsTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'propertyTabsTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    selectors({
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames ?? []],
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as TaxonomicFilterLogicProps['propertyAllowList'],
        ],
        featureFlagPropertyTaxonomicGroups: [
            (s) => [s.currentProjectId, s.eventNames, s.excludedProperties],
            (projectId, eventNames, excludedProperties): TaxonomicFilterGroup[] => [
                {
                    name: 'Feature flags',
                    searchPlaceholder: 'feature flags',
                    type: TaxonomicFilterGroupType.EventFeatureFlags,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        is_feature_flag: true,
                        ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                    }).url,
                    scopedEndpoint:
                        eventNames.length > 0
                            ? combineUrl(`api/projects/${projectId}/property_definitions`, {
                                  event_names: eventNames,
                                  is_feature_flag: true,
                                  filter_by_event_names: true,
                              }).url
                            : undefined,
                    expandLabel: ({ count, expandedCount }: { count: number; expandedCount: number }) =>
                        `Show ${pluralize(expandedCount - count, 'property', 'properties')} that ${pluralize(
                            expandedCount - count,
                            'has',
                            'have',
                            false
                        )}n't been seen with ${pluralize(eventNames.length, 'this event', 'these events', false)}`,
                    getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    excludedProperties:
                        excludedProperties?.[TaxonomicFilterGroupType.EventFeatureFlags]?.filter(isString),
                    ...propertyTaxonomicGroupProps(),
                },
            ],
        ],
        numericalAndPersonPropertyTaxonomicGroups: [
            (s) => [s.currentProjectId, s.eventNames, s.propertyAllowList],
            (projectId, eventNames, propertyAllowList): TaxonomicFilterGroup[] => [
                {
                    name: 'Numerical event properties',
                    searchPlaceholder: 'numerical event properties',
                    type: TaxonomicFilterGroupType.NumericalEventProperties,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        is_numerical: true,
                        event_names: eventNames,
                    }).url,
                    getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    ...propertyTaxonomicGroupProps(),
                },
                {
                    name: 'Person properties',
                    searchPlaceholder: 'person properties',
                    type: TaxonomicFilterGroupType.PersonProperties,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        type: 'person',
                        properties: propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]
                            ? propertyAllowList[TaxonomicFilterGroupType.PersonProperties].join(',')
                            : undefined,
                        exclude_hidden: true,
                        exclude_restricted: true,
                    }).url,
                    getName: (personProperty: PersonProperty) => personProperty.name,
                    getValue: (personProperty: PersonProperty) => personProperty.name,
                    propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]?.filter(isString),
                    ...propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties),
                },
            ],
        ],
    }),
])

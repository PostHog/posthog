import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import { buildEventTypeFilterShortcuts } from 'lib/components/TaxonomicFilter/eventTypeShortcuts'
import {
    TRAFFIC_TYPE_VIRTUAL_PROPERTIES,
    propertyTaxonomicGroupProps,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { withKeywordShortcuts } from 'lib/components/TaxonomicFilter/withKeywordShortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isString, pluralize } from 'lib/utils'
import { getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { getProductEventPropertyFilterOptions } from 'scenes/hog-functions/filters/HogFunctionFiltersInternal'
import { projectLogic } from 'scenes/projectLogic'

import { PropertyDefinition } from '~/types'

import type { eventPropertiesTaxonomicGroupsLogicType } from './eventPropertiesTaxonomicGroupsLogicType'

export const eventPropertiesTaxonomicGroupsLogic = kea<eventPropertiesTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'eventPropertiesTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
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
        eventPropertiesTaxonomicGroups: [
            (s) => [s.currentProjectId, s.featureFlags, s.eventNames, s.excludedProperties, s.propertyAllowList],
            (projectId, featureFlags, eventNames, excludedProperties, propertyAllowList): TaxonomicFilterGroup[] => [
                {
                    name: 'Event properties',
                    searchPlaceholder: 'event properties',
                    type: TaxonomicFilterGroupType.EventProperties,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        is_feature_flag: false,
                        ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                        properties: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]
                            ? propertyAllowList[TaxonomicFilterGroupType.EventProperties].join(',')
                            : undefined,
                        exclude_hidden: true,
                        exclude_restricted: true,
                    }).url,
                    scopedEndpoint:
                        eventNames.length > 0
                            ? combineUrl(`api/projects/${projectId}/property_definitions`, {
                                  event_names: eventNames,
                                  is_feature_flag: false,
                                  filter_by_event_names: true,
                                  properties: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]
                                      ? propertyAllowList[TaxonomicFilterGroupType.EventProperties].join(',')
                                      : undefined,
                                  exclude_hidden: true,
                                  exclude_restricted: true,
                              }).url
                            : undefined,
                    expandLabel: ({ count, expandedCount }: { count: number; expandedCount: number }) =>
                        `Show ${pluralize(expandedCount - count, 'property', 'properties')} that ${pluralize(
                            expandedCount - count,
                            'has',
                            'have',
                            false
                        )}n't been seen with ${pluralize(eventNames.length, 'this event', 'these events', false)}`,
                    excludedProperties: [
                        ...(excludedProperties?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString) ?? []),
                        ...(!featureFlags[FEATURE_FLAGS.TRAFFIC_TYPE_VIRTUAL_PROPERTIES]
                            ? TRAFFIC_TYPE_VIRTUAL_PROPERTIES
                            : []),
                    ],
                    propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString),
                    ...withKeywordShortcuts<PropertyDefinition>(
                        {
                            getName: (propertyDefinition) => propertyDefinition.name,
                            getValue: (propertyDefinition) => propertyDefinition.name,
                            ...propertyTaxonomicGroupProps(),
                        },
                        {
                            popoverHeader: 'Event type shortcut',
                            buildShortcuts: buildEventTypeFilterShortcuts,
                        }
                    ),
                },
                {
                    name: 'Internal event properties',
                    searchPlaceholder: 'internal event properties',
                    type: TaxonomicFilterGroupType.InternalEventProperties,
                    options: getProductEventPropertyFilterOptions('activity-log').map((value) => ({
                        name: value,
                        value,
                        group: TaxonomicFilterGroupType.EventProperties,
                    })),
                    getIcon: getPropertyDefinitionIcon,
                    getPopoverHeader: () => 'Internal event properties',
                },
            ],
        ],
    }),
])

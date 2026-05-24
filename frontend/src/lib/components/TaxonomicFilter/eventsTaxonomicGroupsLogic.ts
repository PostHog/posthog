import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import { buildAutocaptureSeriesShortcuts } from 'lib/components/TaxonomicFilter/eventTypeShortcuts'
import { eventTaxonomicGroupProps } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { withKeywordShortcuts } from 'lib/components/TaxonomicFilter/withKeywordShortcuts'
import { isString } from 'lib/utils'
import { getProductEventFilterOptions } from 'scenes/hog-functions/filters/HogFunctionFiltersInternal'
import { projectLogic } from 'scenes/projectLogic'

import { EventDefinitionType } from '~/types'

import type { eventsTaxonomicGroupsLogicType } from './eventsTaxonomicGroupsLogicType'

export const eventsTaxonomicGroupsLogic = kea<eventsTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'eventsTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    selectors({
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        eventsTaxonomicGroups: [
            (s) => [s.currentProjectId, s.excludedProperties],
            (projectId, excludedProperties): TaxonomicFilterGroup[] => [
                {
                    name: 'Events',
                    searchPlaceholder: 'events',
                    type: TaxonomicFilterGroupType.Events,
                    options: [{ name: 'All events', value: null }].filter(
                        (o) => !excludedProperties[TaxonomicFilterGroupType.Events]?.includes(o.value)
                    ),
                    endpoint: combineUrl(`api/projects/${projectId}/event_definitions`, {
                        event_type: EventDefinitionType.Event,
                        exclude_hidden: true,
                    }).url,
                    excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.Events]?.filter(isString) ?? [],
                    ...withKeywordShortcuts<Record<string, any>>(
                        {
                            getName: (eventDefinition) => eventDefinition.name,
                            getValue: (eventDefinition) =>
                                'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                            getIcon: eventTaxonomicGroupProps.getIcon,
                            getPopoverHeader: eventTaxonomicGroupProps.getPopoverHeader,
                        },
                        {
                            popoverHeader: 'Autocapture shortcut',
                            buildShortcuts: buildAutocaptureSeriesShortcuts,
                        }
                    ),
                },
                {
                    name: 'Internal Events',
                    searchPlaceholder: 'internal events',
                    type: TaxonomicFilterGroupType.InternalEvents,
                    options: [
                        { name: 'All internal events', value: null },
                        ...getProductEventFilterOptions('activity-log').map((item) => ({
                            name: item.label,
                            value: item.value,
                        })),
                    ],
                    getName: (eventDefinition: Record<string, any>) => eventDefinition.name,
                    getValue: (eventDefinition: Record<string, any>) =>
                        'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                    ...eventTaxonomicGroupProps,
                },
            ],
        ],
    }),
])

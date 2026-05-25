import { connect, kea, key, path, props, selectors } from 'kea'

import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { getDistinctPrimaryPropertiesForEvents } from 'lib/utils/primaryEventProperty'

import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'

import type { suggestedFiltersTaxonomicGroupsLogicType } from './suggestedFiltersTaxonomicGroupsLogicType'

export const suggestedFiltersTaxonomicGroupsLogic = kea<suggestedFiltersTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'suggestedFiltersTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [primaryEventPropertiesModel, ['primaryProperties']],
    })),

    selectors({
        suggestedFiltersLabel: [
            () => [(_, props) => props.suggestedFiltersLabel],
            (suggestedFiltersLabel) => suggestedFiltersLabel,
        ],
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames ?? []],
        primaryPropertiesForContextEvents: [
            (s) => [s.eventNames, s.primaryProperties],
            (eventNames: string[], primaryProperties: Record<string, string>): string[] =>
                getDistinctPrimaryPropertiesForEvents(eventNames, primaryProperties),
        ],
        suggestedFiltersTaxonomicGroups: [
            (s) => [s.suggestedFiltersLabel, s.eventNames, s.primaryPropertiesForContextEvents],
            (
                suggestedFiltersLabel: string | undefined,
                eventNames: string[],
                primaryPropertiesForContextEvents: string[]
            ): TaxonomicFilterGroup[] => [
                {
                    name: suggestedFiltersLabel ?? 'Suggested filters',
                    searchPlaceholder: (suggestedFiltersLabel ?? 'Suggested filters').toLowerCase(),
                    categoryLabel: (count: number) =>
                        (suggestedFiltersLabel ?? 'Suggested filters') + (count > 0 ? `: ${count}` : ''),
                    type: TaxonomicFilterGroupType.SuggestedFilters,
                    isLocalOnly: true,
                    isMetaGroup: true,
                    options: [
                        // Promoted properties for any event in context come first — if a team
                        // has marked a property as the one that summarises this event, it's
                        // the property they almost certainly want to filter or break down by.
                        ...primaryPropertiesForContextEvents.map((name) => ({
                            name,
                            group: TaxonomicFilterGroupType.EventProperties,
                        })),
                        ...(eventNames.includes('$autocapture')
                            ? (['text', 'selector'] as const).map((name) => ({
                                  name,
                                  group: TaxonomicFilterGroupType.Elements,
                              }))
                            : []),
                    ],
                    getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
                    getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
                        'name' in item ? (item.name ?? null) : null,
                    getPopoverHeader: () => suggestedFiltersLabel ?? 'Suggested filters',
                },
            ],
        ],
    }),
])

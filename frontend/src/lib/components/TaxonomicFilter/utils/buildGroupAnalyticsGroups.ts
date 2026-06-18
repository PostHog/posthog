import { combineUrl } from 'kea-router'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { toParams } from 'lib/utils/url'
import { getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'

import { Group, GroupType } from '~/types'

export type AggregationLabel = (groupTypeIndex: number) => { singular: string; plural: string }

/**
 * Pure builder for the dynamic "Group Names" tabs (one per group_type_index).
 * Mirrors the `groupAnalyticsTaxonomicGroupNames` selector in taxonomicFilterLogic.
 */
export function buildGroupAnalyticsTaxonomicGroupNames(
    groupTypes: Map<unknown, GroupType>,
    teamId: number,
    aggregationLabel: AggregationLabel
): TaxonomicFilterGroup[] {
    return Array.from(groupTypes.values()).map((type) => ({
        name: capitalizeFirstLetter(aggregationLabel(type.group_type_index).plural),
        searchPlaceholder: aggregationLabel(type.group_type_index).plural,
        type: `${TaxonomicFilterGroupType.GroupNamesPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
        endpoint: combineUrl(`api/environments/${teamId}/groups/`, {
            group_type_index: type.group_type_index,
        }).url,
        getPopoverHeader: () => 'Group Names',
        getName: (group: Group) => groupDisplayId(group.group_key, group.group_properties),
        getValue: (group: Group) => group.group_key,
        groupTypeIndex: type.group_type_index,
    }))
}

/**
 * Pure builder for the dynamic "Group properties" tabs (one per group_type_index).
 * Mirrors the `groupAnalyticsTaxonomicGroups` selector in taxonomicFilterLogic.
 */
export function buildGroupAnalyticsTaxonomicGroups(
    groupTypes: Map<unknown, GroupType>,
    projectId: number | null,
    aggregationLabel: AggregationLabel
): TaxonomicFilterGroup[] {
    return Array.from(groupTypes.values()).map((type) => ({
        name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
        searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
        type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
        endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
            type: 'group',
            group_type_index: type.group_type_index,
            exclude_hidden: true,
        }).url,
        valuesEndpoint: (key) =>
            `api/projects/${projectId}/groups/property_values?${toParams({
                key,
                group_type_index: type.group_type_index,
            })}`,
        getName: (group) => group.name,
        getValue: (group) => group.name,
        getPopoverHeader: () => 'Property',
        getIcon: getPropertyDefinitionIcon,
        groupTypeIndex: type.group_type_index,
    }))
}

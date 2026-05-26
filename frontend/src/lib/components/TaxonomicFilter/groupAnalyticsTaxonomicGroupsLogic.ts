import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter, toParams } from 'lib/utils'
import { getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

import type { groupAnalyticsTaxonomicGroupsLogicType } from './groupAnalyticsTaxonomicGroupsLogicType'

export const groupAnalyticsTaxonomicGroupsLogic = kea<groupAnalyticsTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'groupAnalyticsTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            projectLogic,
            ['currentProjectId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
        ],
    })),

    selectors({
        groupAnalyticsTaxonomicGroupNames: [
            (s) => [s.groupTypes, s.currentTeamId, s.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): TaxonomicFilterGroup[] =>
                Array.from(groupTypes.values()).map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).plural)}`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).plural}`,
                    type: `${TaxonomicFilterGroupType.GroupNamesPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    endpoint: combineUrl(`api/environments/${teamId}/groups/`, {
                        group_type_index: type.group_type_index,
                    }).url,
                    getPopoverHeader: () => `Group Names`,
                    getName: (group: Group) => groupDisplayId(group.group_key, group.group_properties),
                    getValue: (group: Group) => group.group_key,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        groupAnalyticsTaxonomicGroups: [
            (s) => [s.groupTypes, s.currentProjectId, s.aggregationLabel],
            (groupTypes, projectId, aggregationLabel): TaxonomicFilterGroup[] =>
                Array.from(groupTypes.values()).map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        type: 'group',
                        group_type_index: type.group_type_index,
                        exclude_hidden: true,
                        exclude_restricted: true,
                    }).url,
                    valuesEndpoint: (key) =>
                        `api/projects/${projectId}/groups/property_values?${toParams({
                            key,
                            group_type_index: type.group_type_index,
                        })}`,
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                    getPopoverHeader: () => `Property`,
                    getIcon: getPropertyDefinitionIcon,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
    }),
])

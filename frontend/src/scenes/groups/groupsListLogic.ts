import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { DataTableNode } from '~/queries/schema/schema-general'
import { GroupType } from '~/types'

import type { groupsListLogicType } from './groupsListLogicType'

export interface GroupsListLogicProps {
    groupType: GroupType | undefined
}

export const groupsListLogic = kea<groupsListLogicType>([
    props({} as GroupsListLogicProps),
    key((props: GroupsListLogicProps) => props.groupType?.group_type_index ?? 0),
    path(['groups', 'groupsListLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'groupTypeColumns', 'aggregationLabel'],
            groupsAccessLogic,
            ['groupsEnabled'],
        ],
    }),
    actions(() => ({
        setQuery: (query: DataTableNode) => ({ query }),
    })),
    reducers({
        query: [
            (_: any, props: GroupsListLogicProps) =>
                ({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.GroupsQuery,
                        select: props.groupType?.default_columns || defaultDataTableColumns(NodeKind.GroupsQuery),
                        group_type_index: props.groupType?.group_type_index,
                    },
                    full: true,
                    showEventFilter: false,
                    showPersistentColumnConfigurator: true,
                    propertiesViaUrl: true,
                } as DataTableNode),
            { setQuery: (_, { query }) => query },
        ],
    }),
    selectors({
        groupTypeName: [
            (s, p) => [s.aggregationLabel, p.groupType],
            (aggregationLabel, groupType): string =>
                groupType ? aggregationLabel(groupType.group_type_index).singular : 'Group',
        ],
    }),
])

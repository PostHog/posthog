import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { DataTableNode } from '~/queries/schema/schema-general'
import { GroupTypeIndex } from '~/types'

import type { groupsListLogicType } from './groupsListLogicType'

export interface GroupsListLogicProps {
    groupTypeIndex: GroupTypeIndex
}

export const groupsListLogic = kea<groupsListLogicType>([
    props({} as GroupsListLogicProps),
    key((props: GroupsListLogicProps) => props.groupTypeIndex),
    path(['groups', 'groupsListLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupsAccessLogic,
            ['groupsEnabled'],
        ],
    })),
    actions(() => ({
        setQuery: (query: DataTableNode) => ({ query }),
        setQueryWasModified: (queryWasModified: boolean) => ({ queryWasModified }),
    })),
    reducers({
        query: [
            (_: any, props: GroupsListLogicProps) =>
                ({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.GroupsQuery,
                        select: undefined,
                        group_type_index: props.groupTypeIndex,
                    },
                    full: true,
                    showEventFilter: false,
                    showPersistentColumnConfigurator: true,
                    propertiesViaUrl: true,
                } as DataTableNode),
            { setQuery: (_, { query }) => query },
        ],
        queryWasModified: [
            false,
            {
                setQueryWasModified: (_, { queryWasModified }) => queryWasModified,
            },
        ],
    }),
    listeners(({ actions }) => ({
        setQuery: () => {
            actions.setQueryWasModified(true)
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.query.source.kind === NodeKind.GroupsQuery && values.query.source.select === undefined) {
            const defaultColumns = values.groupTypes.get(
                values.query.source.group_type_index as GroupTypeIndex
            )?.default_columns
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.query.source,
                    select: defaultColumns ?? defaultDataTableColumns(NodeKind.GroupsQuery),
                },
            })
            actions.setQueryWasModified(false)
        }
    }),
])

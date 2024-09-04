import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { Node } from '~/queries/schema'

import type { groupsConfigurationLogicType } from './groupsConfigurationLogicType'

export type GroupsConfigurationLogicProps = {
    groupTypeIndex: number
}

export const groupsConfigurationLogic = kea<groupsConfigurationLogicType>([
    props({} as groupsConfigurationLogicType),
    key((props) => `${props.groupTypeIndex}`),
    path((key) => ['scenes', 'groups', 'groupsConfigurationLogic', key]),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
            dataWarehouseJoinsLogic,
            ['joins'],
        ],
        actions: [dataWarehouseJoinsLogic, ['loadJoins']],
    }),

    actions(() => ({
        setGroupTab: (groupTab: string | null) => ({ groupTab }),
        setGroupEventsQuery: (query: Node) => ({ query }),
    })),

    reducers({
        groupTab: [
            null as string | null,
            {
                setGroupTab: (_, { groupTab }) => groupTab,
            },
        ],
    }),
    selectors((props) => ({
        logicProps: [() => [(_, props) => props], (props): GroupsConfigurationLogicProps => props],

        groupJoins: [
            (s) => [s.joins],
            (joins) => joins.filter((join) => join.group_type_index === props.groupTypeIndex),
        ],
    })),
])

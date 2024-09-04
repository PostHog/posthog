import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { Node } from '~/queries/schema'

import type { groupsLogicType } from './groupsLogicType'

export type GroupLogicProps = {
    groupTypeIndex: number
    groupKey: string
}

export const groupsLogic = kea<groupsLogicType>([
    props({} as GroupLogicProps),
    key((props) => `${props.groupTypeIndex}`),
    path((key) => ['scenes', 'groups', 'groupLogic', key]),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
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
    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupLogicProps => props],
    }),
    urlToAction(({ actions }) => ({
        '/groups/:groupTypeIndex/overview': () => {
            actions.setGroupTab('overview')
        },
        '/groups/:groupTypeIndex/list': () => {
            actions.setGroupTab('list')
        },
        '/groups/:groupTypeIndex/config': () => {
            actions.setGroupTab('config')
        },
    })),
])

import { actions, connect, kea, path, props, reducers } from 'kea'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),
    props({} as DataNodeLogicProps),

    connect((props: DataNodeLogicProps) => ({
        con
        values: [dataNodeLogic(props), ['response']],
    })),

    actions({}),
    reducers({}),
])

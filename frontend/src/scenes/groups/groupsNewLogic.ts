import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
// import api from 'lib/api'

import type { groupsNewLogicType } from './groupsNewLogicType'

export type GroupsNewLogicProps = {
    groupTypeIndex: number
}

export const groupsNewLogic = kea<groupsNewLogicType>([
    props({} as GroupsNewLogicProps),
    key((props) => `${props.groupTypeIndex}-new`),
    path((key) => ['scenes', 'groupsNew', 'groupsNewLogic', key]),
    connect(() => ({})),
    actions(() => ({})),
    loaders(() => ({})),
    listeners(() => ({})),
    reducers({}),
    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupsNewLogicProps => props],
    }),
    urlToAction(() => ({})),
    afterMount(() => {}),
])

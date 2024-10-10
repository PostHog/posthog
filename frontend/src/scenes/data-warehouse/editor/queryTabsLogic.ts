import { actions, connect, kea, path, reducers } from 'kea'

import type { queryTabsLogicType } from './queryTabsLogicType'
import { sourceNavigatorLogic } from './sourceNavigatorLogic'

export const queryTabsLogic = kea<queryTabsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryTabsLogic']),
    connect({
        values: [sourceNavigatorLogic, ['navigatorWidth']],
    }),
    actions({
        setWidth: (width: number) => ({ width }),
    }),
    reducers({
        queryPaneWidth: [
            200,
            {
                setWidth: (_, { width }: { width: number }) => width,
            },
        ],
    }),
])

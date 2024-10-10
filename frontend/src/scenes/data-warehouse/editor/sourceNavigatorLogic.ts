import { kea } from 'kea'

import type { sourceNavigatorLogicType } from './sourceNavigatorLogicType'

export const sourceNavigatorLogic = kea<sourceNavigatorLogicType>({
    path: ['scenes', 'data-warehouse', 'editor', 'sourceNavigatorLogic'],
    actions: {
        setWidth: (width: number) => ({ width }),
    },
    reducers: {
        navigatorWidth: [
            200,
            {
                setWidth: (_, { width }: { width: number }) => width,
            },
        ],
    },
})

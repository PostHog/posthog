import { actions, kea, path, reducers } from 'kea'

import type { hedgehogbuddyLogicType } from './hedgehogbuddyLogicType'

export const hedgehogbuddyLogic = kea<hedgehogbuddyLogicType>([
    path(['hedgehog', 'hedgehogbuddyLogic']),

    actions({
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
    }),

    reducers(({}) => ({
        hedgehogModeEnabled: [
            false as boolean,
            { persist: true },
            {
                setHedgehogModeEnabled: (_, { enabled }) => enabled,
            },
        ],
    })),
])

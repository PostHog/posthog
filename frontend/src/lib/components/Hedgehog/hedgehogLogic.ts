import { actions, kea, path, reducers } from 'kea'

import type { hedgehogLogicType } from './hedgehogLogicType'

export const hedgehogLogic = kea<hedgehogLogicType>([
    path(['hedgehog', 'hedgehogLogic']),

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

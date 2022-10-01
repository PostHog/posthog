import { actions, kea, path, reducers } from 'kea'

export const hedgehogbuddyLogic = kea([
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

import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { hedgedHogLogicType } from './hedgedHogLogicType'

export interface HedgedHogData {
    name: string
    value: number
}

export const hedgedHogLogic = kea<hedgedHogLogicType>([
    path(['scenes', 'hedged-hog', 'hedgedHogLogic']),

    actions({
        setData: (data: HedgedHogData) => ({ data }),
    }),

    reducers({
        hedgedHogData: [
            { name: 'Sample HedgedHog', value: 42 } as HedgedHogData,
            {
                setData: (_, { data }) => data,
            },
        ],
    }),

    loaders(() => ({
        hedgedHogData: {
            loadHedgedHogData: async () => {
                // Replace with actual API call when ready
                await new Promise((resolve) => setTimeout(resolve, 500))
                return { name: 'Loaded HedgedHog', value: Math.floor(Math.random() * 100) }
            },
        },
    })),

    selectors({
        dataMessage: [(s) => [s.hedgedHogData], (data: HedgedHogData) => `${data.name}: ${data.value}`],
    }),
])

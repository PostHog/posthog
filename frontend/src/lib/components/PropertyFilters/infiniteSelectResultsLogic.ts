import { kea } from 'kea'
import { SelectResultGroup } from './components/InfiniteSelectResults'

import { infiniteSelectResultsLogicType } from './infiniteSelectResultsLogicType'

export const infiniteSelectResultsLogic = kea<infiniteSelectResultsLogicType>({
    props: {} as {
        pageKey: string
        groups: SelectResultGroup[]
        initialActiveTabKey: string
    },
    key: (props) => props.pageKey,

    actions: () => ({
        setActiveTabKey: (activeTabKey: string) => ({ activeTabKey }),
    }),

    reducers: ({ props }) => ({
        activeTabKey: [
            props.initialActiveTabKey,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
            },
        ],
    }),
})

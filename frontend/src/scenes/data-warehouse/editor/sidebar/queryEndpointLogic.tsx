import { actions, connect, kea, path, props, reducers } from 'kea'

import type { queryEndpointLogicType } from './queryEndpointLogicType'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface QueryEndpointLogicProps {}

export const queryEndpointLogic = kea<queryEndpointLogicType>([
    path(['data-warehouse', 'editor', 'sidebar', 'queryEndpointLogic']),
    props({} as QueryEndpointLogicProps),

    connect(() => ({
        values: [],
    })),
    actions({
        setQueryEndpointName: (queryEndpointName: string) => ({ queryEndpointName }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
    }),
    reducers({
        queryEndpointName: [null, { setQueryEndpointName: (_, { queryEndpointName }) => queryEndpointName }],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
    }),
])

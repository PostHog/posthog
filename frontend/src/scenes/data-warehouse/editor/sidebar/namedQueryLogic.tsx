import { actions, connect, kea, path, props, reducers } from 'kea'

import type { namedQueryLogicType } from './namedQueryLogicType'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface NamedQueryLogicProps {}

export const namedQueryLogic = kea<namedQueryLogicType>([
    path(['data-warehouse', 'editor', 'sidebar', 'namedQueryLogic']),
    props({} as NamedQueryLogicProps),

    connect(() => ({
        values: [],
    })),
    actions({
        setNamedQueryName: (namedQueryName: string) => ({ namedQueryName }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
    }),
    reducers({
        namedQueryName: [null, { setNamedQueryName: (_, { namedQueryName }) => namedQueryName }],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
    }),
])

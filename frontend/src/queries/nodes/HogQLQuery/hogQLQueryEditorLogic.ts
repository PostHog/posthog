import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { HogQLQuery } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'

export interface HogQLQueryEditorLogicProps {
    key: number
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
}

export const hogQLQueryEditorLogic = kea<hogQLQueryEditorLogicType>([
    path(['queries', 'nodes', 'HogQLQuery', 'hogQLQueryEditorLogic']),
    props({} as HogQLQueryEditorLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.query.query !== oldProps.query.query) {
            actions.setQueryInput(props.query.query)
        }
    }),
    actions({
        saveQuery: true,
        setQueryInput: (queryInput: string) => ({ queryInput }),
    }),
    reducers(({ props }) => ({
        queryInput: [props.query.query, { setQueryInput: (_, { queryInput }) => queryInput }],
    })),
    listeners(({ actions, props, values }) => ({
        saveQuery: () => {
            actions.setQueryInput(values.queryInput)
            props.setQuery?.({ ...props.query, query: values.queryInput })
        },
    })),
])

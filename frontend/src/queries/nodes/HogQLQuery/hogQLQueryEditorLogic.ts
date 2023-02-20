import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { format } from 'sql-formatter'
import { HogQLQuery } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'

function formatSQL(sql: string): string {
    return format(sql, {
        language: 'mysql',
        tabWidth: 2,
        keywordCase: 'preserve',
        linesBetweenQueries: 2,
        indentStyle: 'tabularRight',
    })
}
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
            actions.setQueryInput(formatSQL(props.query.query))
        }
    }),
    actions({
        saveQuery: true,
        setQueryInput: (queryInput: string) => ({ queryInput }),
    }),
    reducers(({ props }) => ({
        queryInput: [formatSQL(props.query.query), { setQueryInput: (_, { queryInput }) => queryInput }],
    })),
    listeners(({ actions, props, values }) => ({
        saveQuery: () => {
            const formattedQuery = formatSQL(values.queryInput)
            actions.setQueryInput(formattedQuery)
            props.setQuery?.({ ...props.query, query: formattedQuery })
        },
    })),
])

import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { QueryEditorProps } from '~/queries/QueryEditor/QueryEditor'
import { Node } from '~/queries/schema/schema-general'

import type { queryEditorLogicType } from './queryEditorLogicType'

function prettyJSON(source: string): string {
    try {
        return JSON.stringify(JSON.parse(source), null, 2) + '\n'
    } catch {
        return source
    }
}

export interface QueryEditorLogicProps extends QueryEditorProps {
    key: number
}

export const queryEditorLogic = kea<queryEditorLogicType>([
    path(['queries', 'QueryEditor', 'queryEditorLogic']),
    props({} as QueryEditorLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.query !== oldProps.query) {
            actions.setQueryInput(prettyJSON(props.query))
        }
    }),
    actions({
        saveQuery: true,
        setQueryInput: (queryInput: string) => ({ queryInput }),
    }),
    reducers(({ props }) => ({
        queryInput: [prettyJSON(props.query), { setQueryInput: (_, { queryInput }) => queryInput }],
    })),
    selectors({
        parsedQuery: [
            (s) => [s.queryInput],
            (query): { JSONQuery: Node | null; error: string | null } => {
                let JSONQuery: Node | null = null
                let error = null
                try {
                    JSONQuery = JSON.parse(query)
                } catch (e: any) {
                    error = e.message
                }
                return { JSONQuery, error }
            },
        ],
        JSONQuery: [(s) => [s.parsedQuery], ({ JSONQuery }): Node | null => JSONQuery],
        error: [(s) => [s.parsedQuery], ({ error }): string | null => error],
        inputChanged: [(s, p) => [p.query, s.queryInput], (query, queryInput) => query !== queryInput],
    }),
    listeners(({ actions, props, values }) => ({
        saveQuery: () => {
            if (values.error) {
                lemonToast.error(`Error parsing JSON: ${values.error}`)
            } else {
                const withoutFormatting = JSON.stringify(JSON.parse(values.queryInput))
                actions.setQueryInput(prettyJSON(withoutFormatting))
                props.setQuery?.(withoutFormatting)
            }
        },
    })),
])

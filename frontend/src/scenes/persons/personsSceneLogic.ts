import { actions, kea, path, reducers } from 'kea'

import { actionToUrl, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { objectsEqual } from 'lib/utils'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import type { personsSceneLogicType } from './personsSceneLogicType'

const getDefaultQuery = (): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.PersonsNode },
    full: true,
    columns: undefined,
    propertiesViaUrl: true,
})

export const personsSceneLogic = kea<personsSceneLogicType>([
    path(['scenes', 'persons', 'personsSceneLogic']),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ query: [getDefaultQuery() as Node, { setQuery: (_, { query }) => query }] }),

    actionToUrl(({ values }) => ({
        setQuery: () => [
            urls.persons(),
            {},
            objectsEqual(values.query, getDefaultQuery()) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.persons()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    // set the default unless it's already there
                    if (!objectsEqual(values.query, getDefaultQuery())) {
                        actions.setQuery(getDefaultQuery())
                    }
                } else {
                    if (typeof queryParam === 'object') {
                        actions.setQuery(queryParam)
                    } else {
                        lemonToast.error('Invalid query in URL')
                        console.error({ queryParam })
                    }
                }
            }
        },
    })),
])

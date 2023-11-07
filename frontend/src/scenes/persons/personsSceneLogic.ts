import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { actionToUrl, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { objectsEqual } from 'lib/utils'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import type { personsSceneLogicType } from './personsSceneLogicType'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const getDefaultQuery = (usePersonsQuery = false): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: usePersonsQuery
        ? { kind: NodeKind.PersonsQuery, select: defaultDataTableColumns(NodeKind.PersonsQuery) }
        : { kind: NodeKind.PersonsNode },
    full: true,
    propertiesViaUrl: true,
})

export const personsSceneLogic = kea<personsSceneLogicType>([
    path(['scenes', 'persons', 'personsSceneLogic']),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),
    selectors({
        queryFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags?.[FEATURE_FLAGS.PERSONS_HOGQL_QUERY],
        ],
    }),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers(({ selectors }) => ({
        query: [
            ((state: Record<string, any>) => getDefaultQuery(selectors.queryFlagEnabled(state))) as any as Node,
            { setQuery: (_, { query }) => query },
        ],
    })),

    actionToUrl(({ values }) => ({
        setQuery: () => [
            urls.persons(),
            {},
            objectsEqual(values.query, getDefaultQuery(values.queryFlagEnabled)) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.persons()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    const defaultQuery = getDefaultQuery(values.queryFlagEnabled)
                    // set the default unless it's already there
                    if (!objectsEqual(values.query, defaultQuery)) {
                        actions.setQuery(defaultQuery)
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

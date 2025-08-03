import { actions, events, kea, key, path, props, reducers } from 'kea'

import type { addPersonToCohortModalLogicType } from './addPersonToCohortModalLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { CohortType, PersonType } from '~/types'

import { DataTableNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode } from '~/queries/utils'

export type AddPersonToCohortModalProps = {
    id?: CohortType['id']
}

export const addPersonToCohortModalLogic = kea<addPersonToCohortModalLogicType>([
    props({} as AddPersonToCohortModalProps),
    path(['scenes', 'cohorts', 'addPersonToCohortModalLogic']),
    key((props) => props.id || 'new'),
    actions({
        showAddPersonToCohortModal: true,
        hideAddPersonToCohortModal: true,
        setQuery: (query: Node) => ({ query }),
    }),
    reducers({
        query: [
            {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    fixedProperties: [],
                    select: ['id', 'person_display_name -- Person'],
                },
                showPropertyFilter: false,
                showEventFilter: false,
                showExport: false,
                showSearch: true,
                showActions: false,
            } as DataTableNode,
            {
                setQuery: (state, { query }) => (isDataTableNode(query) ? query : state),
            },
        ],
        addPersonToCohortModalVisible: [
            false,
            {
                showAddPersonToCohortModal: () => true,
                hideAddPersonToCohortModal: () => false,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        cohortPersons: [
            { next: null, previous: null, results: [] } as PaginatedResponse<PersonType>,
            {
                loadCohortPersons: async () => {
                    if (props.id == null || props.id === 'new') {
                        return values.cohortPersons
                    }
                    const result = await api.cohorts.getCohortPersons(props.id)

                    return result
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCohortPersons()
        },
    })),
])

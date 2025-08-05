import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'

import type { addPersonToCohortModalLogicType } from './addPersonToCohortModalLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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
        addPersonToCohort: (id: string) => ({ id }),
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
                showElapsedTime: false,
                showTimings: false,
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
    listeners(({ props, actions }) => ({
        addPersonToCohort: async ({ id }) => {
            const cohortId = props.id
            if (cohortId == null || cohortId === 'new') {
                return
            }
            const response = await api.cohorts.addPersonsToStaticCohort(cohortId, [id])
            await actions.loadCohortPersons()
            if (response) {
                lemonToast.success('Person added to cohort')
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCohortPersons()
        },
    })),
])

import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode } from '~/queries/utils'
import { CohortType, PersonType } from '~/types'

import type { addPersonToCohortModalLogicType } from './addPersonToCohortModalLogicType'
import { cohortEditLogic } from './cohortEditLogic'
import { createCohortDataNodeLogicKey } from './cohortUtils'

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
        setCohortUpdateLoading: (personId: string, loading: boolean) => ({ personId, loading }),
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
        cohortUpdatesInProgress: [
            {} as Record<string, boolean>,
            {
                setCohortUpdateLoading: (state, { personId, loading }) => ({
                    ...state,
                    [personId]: loading,
                }),
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
            actions.setCohortUpdateLoading(id, true)
            const cohortId = props.id
            if (cohortId == null || cohortId === 'new') {
                return
            }
            try {
                const response = await api.cohorts.addPersonsToStaticCohort(cohortId, [id])
                await actions.loadCohortPersons()
                if (response) {
                    lemonToast.success('Person added to cohort')
                    const mountedCohortEditLogic = cohortEditLogic.findMounted({ id: cohortId })
                    await mountedCohortEditLogic?.actions.updateCohortCount()

                    const mountedDataNodeLogic = dataNodeLogic.findMounted({
                        key: createCohortDataNodeLogicKey(cohortId),
                    })
                    mountedDataNodeLogic?.actions.loadData('force_blocking')
                }
            } finally {
                actions.setCohortUpdateLoading(id, false)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCohortPersons()
        },
    })),
])

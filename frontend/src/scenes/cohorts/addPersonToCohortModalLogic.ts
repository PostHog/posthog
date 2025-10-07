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
    tabId: string
}

export const addPersonToCohortModalLogic = kea<addPersonToCohortModalLogicType>([
    props({} as AddPersonToCohortModalProps),
    path(['scenes', 'cohorts', 'addPersonToCohortModalLogic']),
    key((props) => {
        // This should not show when props.id === 'new' but we still handle the case
        if (props.id === 'new' || !props.id) {
            return 'new'
        }
        return `${props.id}-${props.tabId}`
    }),
    actions({
        showAddPersonToCohortModal: true,
        hideAddPersonToCohortModal: true,
        setQuery: (query: Node) => ({ query }),
        addPersonsToCohort: () => true,
        setCohortUpdating: (updating: boolean) => ({ updating }),
        addPerson: (personId: string) => ({ personId }),
        removePerson: (personId: string) => ({ personId }),
        resetPersons: () => true,
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
        isCohortUpdating: [
            false,
            {
                setCohortUpdating: (_state, { updating }) => updating,
            },
        ],
        personsToAddToCohort: [
            {} as Record<string, boolean>,
            {
                addPerson: (state, { personId }) => ({
                    ...state,
                    [personId]: true,
                }),
                removePerson: (state, { personId }) => {
                    const newState = { ...state }
                    delete newState[personId]
                    return newState
                },
                resetPersons: () => {
                    return {}
                },
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
    listeners(({ props, actions, values }) => ({
        addPersonsToCohort: async () => {
            const cohortId = props.id
            if (cohortId == null || cohortId === 'new') {
                return
            }
            try {
                actions.setCohortUpdating(true)
                const ids = Object.keys(values.personsToAddToCohort)
                const response = await api.cohorts.addPersonsToStaticCohort(cohortId, ids)
                await actions.loadCohortPersons()
                if (response) {
                    lemonToast.success('Users added to cohort')
                    const mountedCohortEditLogic = cohortEditLogic.findMounted({ id: cohortId, tabId: props.tabId })
                    await mountedCohortEditLogic?.actions.updateCohortCount()

                    const mountedDataNodeLogic = dataNodeLogic.findMounted({
                        key: createCohortDataNodeLogicKey(cohortId),
                    })
                    mountedDataNodeLogic?.actions.loadData('force_blocking')
                }
                actions.hideAddPersonToCohortModal()
                actions.resetPersons()
            } catch (error) {
                console.error('Failed to add person to cohort:', error)
                lemonToast.error('Unable to add person to cohort')
            } finally {
                actions.setCohortUpdating(false)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCohortPersons()
        },
    })),
])

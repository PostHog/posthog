import { actions, events, kea, key, path, props, reducers } from 'kea'

import type { addPersonToCohortModalLogicType } from './addPersonToCohortModalLogicType'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse, PaginatedResponse } from 'lib/api'
import { CohortType, PersonType } from '~/types'

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
        loadPersons: true,
    }),
    reducers({
        addPersonToCohortModalVisible: [
            false,
            {
                showAddPersonToCohortModal: () => true,
                hideAddPersonToCohortModal: () => false,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        persons: [
            { next: null, previous: null, count: 0, results: [], offset: 0 } as CountedPaginatedResponse<PersonType> & {
                offset: number
            },
            {
                loadPersons: async () => {
                    if (props.id == null || props.id === 'new') {
                        return values.persons
                    }
                    const result = { ...(await api.persons.list()), offset: 0 }
                    return result
                },
            },
        ],
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
            actions.loadPersons()
        },
    })),
])

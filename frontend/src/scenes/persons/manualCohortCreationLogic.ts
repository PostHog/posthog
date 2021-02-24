import { kea } from 'kea'
import { manualCohortCreationLogicType } from './manualCohortCreationLogicType'
import { PersonType } from '~/types'
import api from 'lib/api'

export const manualCohortCreationLogic = kea<manualCohortCreationLogicType<PersonType>>({
    actions: {
        selectId: (id: number) => ({ id }),
        removeId: (idToRemove: number) => ({ idToRemove }),
        fetchPeople: true,
        setPeople: (people: PersonType[]) => ({ people }),
        clearCohort: true,
    },
    reducers: {
        selectedIds: [
            [] as number[],
            {
                selectId: (state, { id }) => [...state, id],
                removeId: (state, { idToRemove }) => state.filter((id) => id !== idToRemove),
                clearCohort: () => [],
            },
        ],
        selectedPeople: [
            [] as PersonType[],
            {
                setPeople: ({}, { people }) => people,
                clearCohort: () => [],
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        selectId: async () => actions.fetchPeople(),
        removeId: async () => actions.fetchPeople(),
        fetchPeople: async () => {
            const result = await api.get('api/person?id=' + values.selectedIds.join(','))
            actions.setPeople(result.results)
        },
    }),
})

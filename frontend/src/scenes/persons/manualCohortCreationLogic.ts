import { kea } from 'kea'
import { manualCohortCreationLogicType } from './manualCohortCreationLogicType'
import { PersonType } from '~/types'
import api from 'lib/api'
import { cohortLogic } from 'scenes/persons/cohortLogic'

export const manualCohortCreationLogic = kea<manualCohortCreationLogicType<PersonType>>({
    actions: {
        selectId: (id: number) => ({ id }),
        removeId: (idToRemove: number) => ({ idToRemove }),
        fetchPeople: true,
        setPeople: (people: PersonType[]) => ({ people }),
        clearCohort: true,
        saveCohort: true,
        setCohortName: (cohortName: string) => ({ cohortName }),
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
        cohortName: [
            '' as string,
            {
                setCohortName: ({}, { cohortName }) => cohortName,
                clearCohort: () => '',
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        selectId: async () => actions.fetchPeople(),
        removeId: async () => actions.fetchPeople(),
        fetchPeople: async () => {
            if (values.selectedIds.length) {
                const result = await api.get('api/person?id=' + values.selectedIds.join(','))
                actions.setPeople(result.results)
            } else {
                actions.setPeople([])
            }
        },
        saveCohort: () => {
            const cohortParams = {
                name: values.cohortName,
                is_static: true,
                users: values.selectedIds,
            }
            cohortLogic({
                cohort: {
                    id: 'new',
                    groups: [],
                },
            }).actions.saveCohort(cohortParams)
        },
    }),
})

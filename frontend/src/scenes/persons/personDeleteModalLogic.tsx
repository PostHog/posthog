import { actions, kea, props, reducers, path } from 'kea'
import api from 'lib/api'
import { PersonType } from '~/types'
import { toParams } from 'lib/utils'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import type { personDeleteModalLogicType } from './personDeleteModalLogicType'
import { loaders } from 'kea-loaders'

export interface PersonDeleteModalLogicProps {
    person: PersonType
}
export type PersonDeleteCallback = (person: PersonType, deleteEvents: boolean) => void

export const personDeleteModalLogic = kea<personDeleteModalLogicType>([
    path(['scenes', 'persons', 'personDeleteModalLogic']),
    props({} as PersonDeleteModalLogicProps),
    actions({
        showPersonDeleteModal: (person: PersonType | null, callback?: PersonDeleteCallback) => ({
            person,
            callback,
        }),
        deletePerson: (person: PersonType, deleteEvents: boolean) => ({ person, deleteEvents }),
    }),
    reducers({
        personDeleteModal: [
            null as PersonType | null,
            {
                showPersonDeleteModal: (_, { person }) => person,
            },
        ],
        personDeleteCallback: [
            null as PersonDeleteCallback | null,
            {
                showPersonDeleteModal: (_, { callback }) => callback ?? null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        deletedPerson: [
            null as PersonType | null,
            {
                deletePerson: async ({ person, deleteEvents }) => {
                    const params = deleteEvents ? { delete_events: true } : {}
                    await api.delete(`api/person/${person.id}?${toParams(params)}`)
                    lemonToast.success(
                        <>
                            The person <strong>{asDisplay(person)}</strong> was removed from the project.
                            {deleteEvents
                                ? ' Corresponding events will be deleted on a set schedule during non-peak usage times.'
                                : ' Their ID(s) will be usable again in an hour or so.'}
                        </>
                    )
                    console.log('personDeleteCallback', values.personDeleteCallback)
                    values.personDeleteCallback?.(person, deleteEvents)
                    actions.showPersonDeleteModal(null)
                    return person
                },
            },
        ],
    })),
])

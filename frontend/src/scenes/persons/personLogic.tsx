import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { PersonType } from '~/types'

import type { personLogicType } from './personLogicType'

export interface PersonLogicProps {
    id: string
}

export const personLogic = kea<personLogicType>([
    props({} as PersonLogicProps),
    key((props) => props.id),
    path((key) => ['scenes', 'persons', 'personLogic', key]),
    actions({
        loadPerson: true,
    }),
    loaders(({ props }) => ({
        person: [
            null as PersonType | null,
            {
                loadPerson: async (): Promise<PersonType | null> => {
                    const response = await api.persons.list({ distinct_id: props.id })
                    const person = response.results[0]
                    return person
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPerson()
    }),
])

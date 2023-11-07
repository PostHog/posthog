import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, listeners, events } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { PersonType } from '~/types'
import type { mergeSplitPersonLogicType } from './mergeSplitPersonLogicType'
import { personsLogic } from './personsLogic'

export interface SplitPersonLogicProps {
    person: PersonType
}

export type PersonUuids = NonNullable<PersonType['uuid']>[]

export const mergeSplitPersonLogic = kea<mergeSplitPersonLogicType>([
    props({} as SplitPersonLogicProps),
    key((props) => props.person.id ?? 'new'),
    path((key) => ['scenes', 'persons', 'mergeSplitPersonLogic', key]),
    connect(() => ({
        actions: [
            personsLogic({ syncWithUrl: true }),
            ['setListFilters', 'loadPersons', 'setPerson', 'setSplitMergeModalShown'],
        ],
        values: [personsLogic({ syncWithUrl: true }), ['persons']],
    })),
    actions({
        setSelectedPersonToAssignSplit: (id: string) => ({ id }),
        cancel: true,
    }),
    loaders(({ values, actions }) => ({
        executed: [
            false,
            {
                execute: async () => {
                    const splitAction = await api.create('api/person/' + values.person.id + '/split/', {
                        ...(values.selectedPersonsToAssignSplit
                            ? { main_distinct_id: values.selectedPersonsToAssignSplit }
                            : {}),
                    })
                    if (splitAction.success) {
                        lemonToast.success(
                            'Person succesfully split. This may take up to a couple of minutes to complete.'
                        )
                        eventUsageLogic.actions.reportPersonSplit(values.person.distinct_ids.length)
                        actions.setSplitMergeModalShown(false)
                        router.actions.push('/persons')
                        return true
                    }
                    return false
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        person: [props.person, {}],
        selectedPersonsToAssignSplit: [
            null as null | string,
            {
                setSelectedPersonToAssignSplit: (_, { id }) => id,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setListFilters: () => {
            actions.loadPersons()
        },
        cancel: () => {
            if (!values.executedLoading) {
                actions.setSplitMergeModalShown(false)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: [actions.loadPersons],
    })),
])

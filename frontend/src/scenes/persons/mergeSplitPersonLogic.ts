import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { successToast } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { PersonType } from '~/types'
import { mergeSplitPersonLogicType } from './mergeSplitPersonLogicType'
import { personsLogic } from './personsLogic'

export enum ActivityType {
    SPLIT = 'split',
    MERGE = 'merge',
}

interface SplitPersonLogicProps {
    person: PersonType
}

type PersonIds = NonNullable<PersonType['id']>[]

export const mergeSplitPersonLogic = kea<mergeSplitPersonLogicType<ActivityType, PersonIds, SplitPersonLogicProps>>({
    props: {} as SplitPersonLogicProps,
    key: (props) => props.person.id,
    connect: {
        actions: [personsLogic, ['setListFilters', 'loadPersons', 'setPerson', 'setSplitMergeModalShown']],
        values: [personsLogic, ['persons']],
    },
    actions: {
        setActivity: (activity: ActivityType) => ({ activity }),
        setSelectedPersonsToMerge: (persons: PersonIds) => ({ persons }),
        setSelectedPersonToAssignSplit: (id: string) => ({ id }),
        cancel: true,
    },
    reducers: ({ props }) => ({
        activity: [
            ActivityType.MERGE,
            {
                setActivity: (_, { activity }) => activity,
            },
        ],
        person: [props.person, {}],
        selectedPersonsToMerge: [
            [] as PersonIds,
            {
                setSelectedPersonsToMerge: (_, { persons }) => persons,
            },
        ],
        selectedPersonsToAssignSplit: [
            null as null | string,
            {
                setSelectedPersonToAssignSplit: (_, { id }) => id,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        setListFilters: () => {
            actions.loadPersons()
        },
        cancel: () => {
            if (!values.executedLoading) {
                actions.setSplitMergeModalShown(false)
            }
        },
    }),
    loaders: ({ values, actions }) => ({
        executed: [
            false,
            {
                execute: async () => {
                    if (values.activity === ActivityType.MERGE) {
                        const newPerson = await api.create('api/person/' + values.person.id + '/merge/', {
                            ids: values.selectedPersonsToMerge,
                        })
                        if (newPerson.id) {
                            successToast(
                                'Persons succesfully merged.',
                                'All users have been succesfully merged. Changes should take effect immediately.'
                            )
                            eventUsageLogic.actions.reportPersonMerged(values.selectedPersonsToMerge.length)
                            actions.setSplitMergeModalShown(false)
                            actions.setPerson(newPerson)
                            return true
                        }
                    } else {
                        const splitAction = await api.create('api/person/' + values.person.id + '/split/', {
                            ...(values.selectedPersonsToAssignSplit
                                ? { main_distinct_id: values.selectedPersonsToAssignSplit }
                                : {}),
                        })
                        if (splitAction.success) {
                            successToast(
                                'Person succesfully split.',
                                'We are in the process of splitting this person. It may take up to a couple of minutes to complete.'
                            )
                            eventUsageLogic.actions.reportPersonSplit(values.person.distinct_ids.length)
                            actions.setSplitMergeModalShown(false)
                            router.actions.push('/persons')
                            return true
                        }
                    }
                    return false
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadPersons],
    }),
})

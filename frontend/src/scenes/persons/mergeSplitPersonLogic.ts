import { actions, connect, events, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { PersonType } from '~/types'

import type { mergeSplitPersonLogicType } from './mergeSplitPersonLogicType'
import { personsLogic } from './personsLogic'

export interface SplitPersonLogicProps {
    person: PersonType
    urlId: string
    tabId?: string
}

export type PersonUuids = NonNullable<PersonType['uuid']>[]

export type SplitMode = 'all' | 'partial'

export const mergeSplitPersonLogic = kea<mergeSplitPersonLogicType>([
    props({} as SplitPersonLogicProps),
    key((props) => `${props.tabId ?? 'notab'}:${props.person.id ?? 'new'}`),
    path((key) => ['scenes', 'persons', 'mergeSplitPersonLogic', key]),
    connect((props: SplitPersonLogicProps) => ({
        actions: [
            personsLogic({ syncWithUrl: true, urlId: props.urlId, tabId: props.tabId }),
            ['setListFilters', 'loadPersons', 'setPerson', 'setSplitMergeModalShown'],
        ],
        values: [personsLogic({ syncWithUrl: true, urlId: props.urlId, tabId: props.tabId }), ['persons']],
    })),
    actions({
        setSelectedPersonToAssignSplit: (id: string) => ({ id }),
        setSplitMode: (mode: SplitMode) => ({ mode }),
        setDistinctIdsToSplit: (ids: string[]) => ({ ids }),
        cancel: true,
    }),
    loaders(({ values, actions }) => ({
        executed: [
            false,
            {
                execute: async () => {
                    const payload =
                        values.splitMode === 'partial'
                            ? { distinct_ids_to_split: values.distinctIdsToSplit }
                            : values.selectedPersonToAssignSplit
                              ? { main_distinct_id: values.selectedPersonToAssignSplit }
                              : {}
                    const splitAction = await api.create('api/person/' + values.person.id + '/split/', payload)
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
        selectedPersonToAssignSplit: [
            null as null | string,
            {
                setSelectedPersonToAssignSplit: (_, { id }) => id,
            },
        ],
        splitMode: [
            'all' as SplitMode,
            {
                setSplitMode: (_, { mode }) => mode,
            },
        ],
        distinctIdsToSplit: [
            [] as string[],
            {
                setDistinctIdsToSplit: (_, { ids }) => ids,
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

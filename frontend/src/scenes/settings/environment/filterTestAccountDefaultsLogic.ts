import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { filterTestAccountsDefaultsLogicType } from './filterTestAccountDefaultsLogicType'

export const filterTestAccountsDefaultsLogic = kea<filterTestAccountsDefaultsLogicType>([
    path(['scenes', 'project', 'Settings', 'filterTestAccountsDefaultLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setDefault: (value: boolean) => ({ value }),
        setTeamDefault: (value: boolean) => ({ value }),
        setLocalDefault: (value: boolean) => ({ value }),
    }),
    reducers({
        localFilterTestAccountsDefault: [
            null as null | boolean,
            {
                setDefault: (_, { value }) => value,
                setTeamDefault: (_, { value }) => value,
                setLocalDefault: (_, { value }) => value,
            },
        ],
    }),
    selectors({
        filterTestAccountsDefault: [
            (s) => [s.localFilterTestAccountsDefault, s.currentTeam],
            (localFilterTestAccountsDefault, currentTeam) => {
                if (localFilterTestAccountsDefault !== null) {
                    return localFilterTestAccountsDefault
                } else if (currentTeam?.test_account_filters_default_checked) {
                    return currentTeam?.test_account_filters_default_checked
                }
                return false
            },
        ],
    }),
    listeners({
        setTeamDefault: ({ value }) => {
            localStorage.setItem('default_filter_test_accounts', value.toString())
        },
        setLocalDefault: ({ value }) => {
            localStorage.setItem('default_filter_test_accounts', value.toString())
        },
    }),
    events(({ actions }) => ({
        afterMount: () => {
            if (localStorage.getItem('default_filter_test_accounts') !== null) {
                actions.setDefault(localStorage.getItem('default_filter_test_accounts') === 'true')
            }
        },
    })),
])

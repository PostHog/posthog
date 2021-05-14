import api from 'lib/api'
import { kea } from 'kea'
import { systemStatusLogicType } from './systemStatusLogicType'
import { userLogic } from 'scenes/userLogic'
import { SystemStatus } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export type TabName = 'overview'

export const systemStatusLogic = kea<systemStatusLogicType<SystemStatus, TabName>>({
    actions: {
        addSystemStatus: (systemStatus: SystemStatus) => ({ systemStatus }),
        setTab: (tab: TabName) => ({ tab }),
    },
    loaders: {
        systemStatus: [
            [] as SystemStatus[],
            {
                loadSystemStatus: async () => {
                    if (preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
                        return []
                    }
                    return (await api.get('_system_status')).results
                },
            },
        ],
    },
    reducers: {
        tab: [
            'overview' as TabName,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        error: [
            null as null | string,
            {
                loadSystemStatusFailure: (_, { error }) => error,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSystemStatus()
        },
    }),

    actionToUrl: ({ values }) => ({
        setTab: () => '/instance/status' + (values.tab === 'overview' ? '' : '/' + values.tab),
    }),

    urlToAction: ({ actions, values }) => ({
        '/instance/status(/:tab)': ({ tab }: { tab?: TabName }) => {
            const currentTab = tab || 'overview'
            if (currentTab !== values.tab) {
                actions.setTab(currentTab)
            }
        },
    }),
})

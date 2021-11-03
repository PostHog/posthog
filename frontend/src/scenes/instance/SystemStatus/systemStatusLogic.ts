import api from 'lib/api'
import { kea } from 'kea'
import { systemStatusLogicType } from './systemStatusLogicType'
import { userLogic } from 'scenes/userLogic'
import {
    SystemStatus,
    SystemStatusRow,
    SystemStatusQueriesResult,
    SystemStatusAnalyzeResult,
    OrganizationType,
    UserType,
    PreflightStatus,
} from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'

export type TabName = 'overview' | 'internal_metrics'

export const systemStatusLogic = kea<systemStatusLogicType<TabName>>({
    path: ['scenes', 'instance', 'SystemStatus', 'systemStatusLogic'],
    actions: {
        setTab: (tab: TabName) => ({ tab }),
        setOpenSections: (sections: string[]) => ({ sections }),
        setAnalyzeModalOpen: (isOpen: boolean) => ({ isOpen }),
        setAnalyzeQuery: (query: string) => ({ query }),
        openAnalyzeModalWithQuery: (query: string) => ({ query }),
    },
    loaders: ({ values }) => ({
        systemStatus: [
            null as SystemStatus | null,
            {
                loadSystemStatus: async () => {
                    if (preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
                        return null
                    }
                    return (await api.get('api/instance_status')).results
                },
            },
        ],
        queries: [
            null as SystemStatusQueriesResult | null,
            {
                loadQueries: async () => (await api.get('api/instance_status/queries')).results,
            },
        ],
        analyzeQueryResult: [
            null as SystemStatusAnalyzeResult | null,
            {
                setAnalyzeModalOpen: () => null,
                runAnalyzeQuery: async () => {
                    return (await api.create('api/instance_status/analyze_ch_query', { query: values.analyzeQuery }))
                        .results
                },
            },
        ],
    }),
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
        openSections: [
            ['0'] as string[],
            { persist: true },
            {
                setOpenSections: (_, { sections }) => sections,
            },
        ],
        analyzeModalOpen: [
            false as boolean,
            {
                setAnalyzeModalOpen: (_, { isOpen }) => isOpen,
                openAnalyzeModalWithQuery: () => true,
            },
        ],
        analyzeQuery: [
            '' as string,
            {
                setAnalyzeQuery: (_, { query }) => query,
                openAnalyzeModalWithQuery: (_, { query }) => query,
            },
        ],
    },

    selectors: () => ({
        overview: [
            (s) => [s.systemStatus],
            (status: SystemStatus | null): SystemStatusRow[] => (status ? status.overview : []),
        ],
        showAnalyzeQueryButton: [
            () => [
                preflightLogic.selectors.preflight,
                organizationLogic.selectors.currentOrganization,
                userLogic.selectors.user,
            ],
            (preflight: PreflightStatus | null, org: OrganizationType | null, user: UserType | null): boolean => {
                if (preflight?.cloud) {
                    return !!user?.is_staff
                }
                return !!org?.membership_level && org.membership_level >= OrganizationMembershipLevel.Admin
            },
        ],
    }),

    listeners: ({ actions }) => ({
        setTab: ({ tab }: { tab: TabName }) => {
            if (tab === 'internal_metrics') {
                actions.loadQueries()
            }
        },
    }),

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

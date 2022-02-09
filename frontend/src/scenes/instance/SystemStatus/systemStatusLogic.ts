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
    InstanceSetting,
} from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { isUserLoggedIn } from 'lib/utils'

export enum ConfigMode {
    View = 'view',
    Edit = 'edit',
}
export interface MetricRow {
    metric: string
    key: string
    value: any
}

export type InstanceStatusTabName = 'overview' | 'internal_metrics' | 'configuration'

/**
 * We whitelist the specific instance settings that can be edited via the /instance/status page.
 * Even if some settings are editable in the frontend according to the API, we may don't want to expose them here.
 * For example: async migrations settings are handled in their own page.
 */
const EDITABLE_INSTANCE_SETTINGS = [
    'RECORDINGS_TTL_WEEKS',
    'EMAIL_ENABLED',
    'EMAIL_HOST',
    'EMAIL_PORT',
    'EMAIL_HOST_USER',
    'EMAIL_HOST_PASSWORD',
    'EMAIL_USE_TLS',
    'EMAIL_USE_SSL',
    'EMAIL_DEFAULT_FROM',
    'EMAIL_REPLY_TO',
]

export const systemStatusLogic = kea<systemStatusLogicType<ConfigMode, InstanceStatusTabName>>({
    path: ['scenes', 'instance', 'SystemStatus', 'systemStatusLogic'],
    actions: {
        setTab: (tab: InstanceStatusTabName) => ({ tab }),
        setOpenSections: (sections: string[]) => ({ sections }),
        setAnalyzeModalOpen: (isOpen: boolean) => ({ isOpen }),
        setAnalyzeQuery: (query: string) => ({ query }),
        openAnalyzeModalWithQuery: (query: string) => ({ query }),
        setInstanceConfigMode: (mode: ConfigMode) => ({ mode }),
        updateInstanceConfigValue: (key: string, value: any) => ({ key, value }),
        clearInstanceConfigEditing: true,
    },
    loaders: ({ values }) => ({
        systemStatus: [
            null as SystemStatus | null,
            {
                loadSystemStatus: async () => {
                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return null
                    }

                    if (preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
                        return null
                    }

                    return (await api.get('api/instance_status')).results ?? null
                },
            },
        ],
        instanceSettings: [
            [] as InstanceSetting[],
            {
                loadInstanceSettings: async () => {
                    return (await api.get('api/instance_settings')).results ?? []
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
            'overview' as InstanceStatusTabName,
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
        instanceConfigMode: [
            // Determines whether the Instance Configuration table on "Configuration" tab is on edit or view mode
            ConfigMode.View,
            {
                setInstanceConfigMode: (_, { mode }) => mode,
            },
        ],
        instanceConfigEditingState: [
            {} as Record<string, Pick<InstanceSetting, 'value'>>,
            {
                updateInstanceConfigValue: (s, { key, value }) => ({ ...s, [key]: value }),
                clearInstanceConfigEditing: () => ({}),
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
        editableInstanceSettings: [
            (s) => [s.instanceSettings],
            (instanceSettings): InstanceSetting[] =>
                instanceSettings.filter((item) => item.editable && EDITABLE_INSTANCE_SETTINGS.includes(item.key)),
        ],
    }),

    listeners: ({ actions }) => ({
        setTab: ({ tab }: { tab: InstanceStatusTabName }) => {
            if (tab === 'internal_metrics') {
                actions.loadQueries()
            }
            actions.setInstanceConfigMode(ConfigMode.View)
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
        '/instance/status(/:tab)': ({ tab }: { tab?: InstanceStatusTabName }) => {
            const currentTab = tab || 'overview'
            if (currentTab !== values.tab) {
                actions.setTab(currentTab)
            }
        },
    }),
})

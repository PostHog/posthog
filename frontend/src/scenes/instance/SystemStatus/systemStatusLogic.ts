import api from 'lib/api'
import { kea } from 'kea'
import type { systemStatusLogicType } from './systemStatusLogicType'
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
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { isUserLoggedIn } from 'lib/utils'
import { lemonToast } from 'lib/components/lemonToast'

export enum ConfigMode {
    View = 'view',
    Edit = 'edit',
    Saving = 'saving',
}
export interface MetricRow {
    metric: string
    key: string
    value?: boolean | string | number | null
}

export type InstanceStatusTabName = 'overview' | 'metrics' | 'settings' | 'staff_users' | 'kafka_inspector'

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
    'AGGREGATE_BY_DISTINCT_IDS_TEAMS',
    'ENABLE_ACTOR_ON_EVENTS_TEAMS',
    'STRICT_CACHING_TEAMS',
    'SLACK_APP_CLIENT_ID',
    'SLACK_APP_CLIENT_SECRET',
]

export const systemStatusLogic = kea<systemStatusLogicType>({
    path: ['scenes', 'instance', 'SystemStatus', 'systemStatusLogic'],
    actions: {
        setTab: (tab: InstanceStatusTabName) => ({ tab }),
        setOpenSections: (sections: string[]) => ({ sections }),
        setAnalyzeModalOpen: (isOpen: boolean) => ({ isOpen }),
        setAnalyzeQuery: (query: string) => ({ query }),
        openAnalyzeModalWithQuery: (query: string) => ({ query }),
        setInstanceConfigMode: (mode: ConfigMode) => ({ mode }),
        updateInstanceConfigValue: (key: string, value?: string | boolean | number) => ({ key, value }),
        clearInstanceConfigEditing: true,
        saveInstanceConfig: true,
        setUpdatedInstanceConfigCount: (count: number | null) => ({ count }),
        increaseUpdatedInstanceConfigCount: true,
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
            ConfigMode.View as ConfigMode,
            {
                setInstanceConfigMode: (_, { mode }) => mode,
            },
        ],
        instanceConfigEditingState: [
            {} as Record<string, string | boolean | number>,
            {
                updateInstanceConfigValue: (s, { key, value }) => {
                    if (value !== undefined) {
                        return { ...s, [key]: value }
                    }
                    const newState = { ...s }
                    delete newState[key]
                    return newState
                },
                clearInstanceConfigEditing: () => ({}),
            },
        ],
        updatedInstanceConfigCount: [
            null as number | null, // Number of config items that have been updated; `null` means no update is in progress
            {
                setUpdatedInstanceConfigCount: (_, { count }) => count,
                loadInstanceSettings: () => null,
                increaseUpdatedInstanceConfigCount: (state) => (state ?? 0) + 1,
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

    listeners: ({ actions, values }) => ({
        setTab: ({ tab }: { tab: InstanceStatusTabName }) => {
            if (tab === 'metrics') {
                actions.loadQueries()
            }
            actions.setInstanceConfigMode(ConfigMode.View)
        },
        updateInstanceConfigValue: ({ key, value }) => {
            const previousValue = values.editableInstanceSettings.find((item) => item.key === key)?.value
            if (value && previousValue == value) {
                actions.updateInstanceConfigValue(key, undefined)
            }
        },
        saveInstanceConfig: async (_, breakpoint) => {
            actions.setUpdatedInstanceConfigCount(0)
            Object.entries(values.instanceConfigEditingState).map(async ([key, value]) => {
                try {
                    await api.update(`api/instance_settings/${key}`, {
                        value,
                    })
                    actions.increaseUpdatedInstanceConfigCount()
                } catch {
                    lemonToast.error('There was an error updating instance settings – please try again')
                    await breakpoint(1000)
                    actions.loadInstanceSettings()
                }
            })
            await breakpoint(1000)
            if (values.updatedInstanceConfigCount === Object.keys(values.instanceConfigEditingState).length) {
                actions.loadInstanceSettings()
                actions.clearInstanceConfigEditing()
                actions.setInstanceConfigMode(ConfigMode.View)
                lemonToast.success('Instance settings updated')
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSystemStatus()
        },
    }),

    actionToUrl: ({ values }) => ({
        setTab: () => '/instance/' + (values.tab === 'overview' ? 'status' : values.tab),
    }),

    urlToAction: ({ actions, values }) => ({
        '/instance(/:tab)': ({ tab }: { tab?: InstanceStatusTabName }) => {
            const currentTab =
                tab && ['metrics', 'settings', 'staff_users', 'kafka_inspector'].includes(tab) ? tab : 'overview'
            if (currentTab !== values.tab) {
                actions.setTab(currentTab)
            }
        },
    }),
})

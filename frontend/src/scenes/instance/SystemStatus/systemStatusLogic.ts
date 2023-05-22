import api from 'lib/api'
import { kea, path, actions, reducers, listeners, events, selectors } from 'kea'
import type { systemStatusLogicType } from './systemStatusLogicType'
import { userLogic } from 'scenes/userLogic'
import { SystemStatus, SystemStatusRow, SystemStatusQueriesResult, InstanceSetting } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isUserLoggedIn } from 'lib/utils'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import { captureException } from '@sentry/react'

export enum ConfigMode {
    View = 'view',
    Edit = 'edit',
    Saving = 'saving',
}

export type InstanceStatusTabName = 'overview' | 'metrics' | 'settings' | 'staff_users' | 'kafka_inspector'

/**
 * We whitelist the specific instance settings that can be edited via the /instance/status page.
 * Even if some settings are editable in the frontend according to the API, we may don't want to expose them here.
 * For example: async migrations settings are handled in their own page.
 */
const EDITABLE_INSTANCE_SETTINGS = [
    'RECORDINGS_TTL_WEEKS',
    'RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS',
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
    'PERSON_ON_EVENTS_ENABLED',
    'GROUPS_ON_EVENTS_ENABLED',
    'STRICT_CACHING_TEAMS',
    'SLACK_APP_CLIENT_ID',
    'SLACK_APP_CLIENT_SECRET',
    'SLACK_APP_SIGNING_SECRET',
    'PARALLEL_DASHBOARD_ITEM_CACHE',
    'RATE_LIMIT_ENABLED',
    'RATE_LIMITING_ALLOW_LIST_TEAMS',
    'SENTRY_AUTH_TOKEN',
    'SENTRY_ORGANIZATION',
    'HEATMAP_SAMPLE_N',
]

// Note: This logic does some heavy calculations - avoid connecting it outside of system status pages!
export const systemStatusLogic = kea<systemStatusLogicType>([
    path(['scenes', 'instance', 'SystemStatus', 'systemStatusLogic']),
    actions({
        setTab: (tab: InstanceStatusTabName) => ({ tab }),
        setOpenSections: (sections: string[]) => ({ sections }),
        setInstanceConfigMode: (mode: ConfigMode) => ({ mode }),
        updateInstanceConfigValue: (key: string, value?: string | boolean | number) => ({ key, value }),
        clearInstanceConfigEditing: true,
    }),
    loaders({
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
    }),
    reducers({
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
    }),

    forms(({ values }) => ({
        instanceConfigSave: {
            submit: async () => {
                await Promise.all(
                    Object.entries(values.instanceConfigEditingState).map(async ([key, value]) => {
                        await api.update(`api/instance_settings/${key}`, {
                            value,
                        })
                        eventUsageLogic.actions.reportInstanceSettingChange(key, value)
                    })
                )
            },
        },
    })),

    selectors({
        overview: [
            (s) => [s.systemStatus],
            (status: SystemStatus | null): SystemStatusRow[] => (status ? status.overview : []),
        ],
        editableInstanceSettings: [
            (s) => [s.instanceSettings],
            (instanceSettings): InstanceSetting[] =>
                instanceSettings.filter((item) => item.editable && EDITABLE_INSTANCE_SETTINGS.includes(item.key)),
        ],
    }),

    listeners(({ actions, values }) => ({
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
        submitInstanceConfigSaveSuccess: () => {
            actions.loadInstanceSettings()
            actions.resetInstanceConfigSave()
            actions.clearInstanceConfigEditing()
            actions.setInstanceConfigMode(ConfigMode.View)
            lemonToast.success('Instance configuration updated')
        },
        submitInstanceConfigSaveFailure: ({ error }) => {
            captureException(error)
            lemonToast.error('There was an error updating instance settings - please try again later')
            actions.loadInstanceSettings()
        },
        setInstanceConfigMode: () => {
            actions.resetInstanceConfigSave()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSystemStatus()
        },
    })),

    actionToUrl(({ values }) => ({
        setTab: () => '/instance/' + (values.tab === 'overview' ? 'status' : values.tab),
    })),

    urlToAction(({ actions, values }) => ({
        '/instance(/:tab)': ({ tab }: { tab?: InstanceStatusTabName }) => {
            const currentTab =
                tab && ['metrics', 'settings', 'staff_users', 'kafka_inspector'].includes(tab) ? tab : 'overview'
            if (currentTab !== values.tab) {
                actions.setTab(currentTab)
            }
        },
    })),
])

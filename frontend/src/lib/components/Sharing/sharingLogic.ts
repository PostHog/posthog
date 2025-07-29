import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getInsightId } from 'scenes/insights/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ExportOptions } from '~/exporter/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature, InsightShortId, SharingConfigurationType } from '~/types'

import type { sharingLogicType } from './sharingLogicType'

export interface SharingLogicProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    recordingId?: string
    additionalParams?: Record<string, any>
}

export interface EmbedConfig extends ExportOptions {
    width: string
    height: string
}

const defaultEmbedConfig: EmbedConfig = {
    width: '100%',
    height: '400',
    whitelabel: false,
    legend: false,
    noHeader: false,
    showInspector: false,
}

const propsToApiParams = async (
    props: SharingLogicProps
): Promise<{ dashboardId?: number; insightId?: number; recordingId?: string }> => {
    const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
    return {
        dashboardId: props.dashboardId,
        insightId,
        recordingId: props.recordingId,
    }
}

export const sharingLogic = kea<sharingLogicType>([
    path(['lib', 'components', 'Sharing', 'sharingLogic']),
    props({} as SharingLogicProps),
    key(
        ({ insightShortId, dashboardId, recordingId }) =>
            `sharing-${insightShortId || dashboardId || recordingId || ''}`
    ),
    connect(() => [preflightLogic, userLogic, dashboardsModel]),

    actions({
        togglePreview: true,
        reloadIframe: true,
    }),
    reducers({
        showPreview: [true, { togglePreview: (state) => !state }],
        iframeKey: [0, { reloadIframe: (state) => state + 1 }],
    }),

    loaders(({ props }) => ({
        sharingConfiguration: [
            null as SharingConfigurationType | null,
            {
                loadSharingConfiguration: async () => {
                    return await api.sharing.get(await propsToApiParams(props))
                },
                setIsEnabled: async (enabled: boolean) => {
                    return await api.sharing.update(await propsToApiParams(props), { enabled })
                },
                updateSettings: async (settings: Record<string, any>) => {
                    return await api.sharing.update(await propsToApiParams(props), { settings })
                },
            },
        ],
    })),
    listeners(({ props, values, actions }) => ({
        setIsEnabled: (enabled) => {
            if (props.dashboardId) {
                eventUsageLogic.actions.reportDashboardShareToggled(enabled)
            }
        },
        setIsEnabledSuccess: () => {
            if (props.dashboardId) {
                dashboardsModel.actions.loadDashboards()
            }
        },
        setEmbedConfigValue: ({ name, value }) => {
            if (name === 'whitelabel' && props.dashboardId) {
                eventUsageLogic.actions.reportDashboardWhitelabelToggled(value)
            }
            if (name === 'whitelabel' && props.insightShortId) {
                eventUsageLogic.actions.reportInsightWhitelabelToggled(value)
            }
            // Auto-save all embed config changes to settings
            if (values.sharingConfiguration) {
                actions.updateSettings({
                    ...values.sharingConfiguration.settings,
                    [name as string]: value,
                })
            }
        },
        updateSettingsSuccess: () => {
            // Reload iframe when settings are updated
            actions.reloadIframe()
        },
        loadSharingConfigurationSuccess: (sharingConfiguration) => {
            if (sharingConfiguration) {
                // Load all options from settings
                actions.setEmbedConfigValues({
                    ...defaultEmbedConfig,
                    ...sharingConfiguration.settings,
                })
            }
        },
    })),

    forms({
        embedConfig: {
            defaults: defaultEmbedConfig,
        },
    }),
    selectors({
        siteUrl: [() => [preflightLogic.selectors.preflight], (preflight) => preflight?.site_url],
        whitelabelAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.WHITE_LABELLING),
        ],
        mergedEmbedConfig: [
            (s) => [s.embedConfig, s.sharingConfiguration],
            (embedConfig, sharingConfiguration) => ({
                ...defaultEmbedConfig,
                ...embedConfig,
                // Merge all options from settings
                ...sharingConfiguration?.settings,
            }),
        ],

        params: [
            (s) => [s.mergedEmbedConfig, (_, props) => props.additionalParams],
            (mergedEmbedConfig, additionalParams = {}) => {
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                const { width, height, whitelabel, noHeader, showInspector, legend, detailed, ...params } =
                    mergedEmbedConfig
                return {
                    ...additionalParams,
                }
            },
        ],
        shareLink: [
            (s) => [s.siteUrl, s.sharingConfiguration, s.params],
            (siteUrl, sharingConfiguration, params) =>
                sharingConfiguration ? siteUrl + urls.shared(sharingConfiguration.access_token, params) : '',
        ],
        embedLink: [
            (s) => [s.siteUrl, s.sharingConfiguration, s.params],
            (siteUrl, sharingConfiguration, params) =>
                sharingConfiguration ? siteUrl + urls.embedded(sharingConfiguration.access_token, params) : '',
        ],
        iframeProperties: [
            (s) => [s.embedLink, s.mergedEmbedConfig, s.iframeKey],
            (embedLink, { width, height }, iframeKey) => ({
                width,
                height,
                frameBorder: 0,
                allowfullscreen: true,
                src: embedLink,
                key: iframeKey,
            }),
        ],
        embedCode: [
            (s) => [s.iframeProperties],
            (iframeProperties) =>
                `<iframe ${Object.entries(iframeProperties)
                    .map(([key, value]) => {
                        if (value === true) {
                            return key.toLowerCase()
                        }
                        return `${key.toLowerCase()}="${String(value).split('"').join('')}"`
                    })
                    .join(' ')}></iframe>`,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSharingConfiguration()
    }),
])

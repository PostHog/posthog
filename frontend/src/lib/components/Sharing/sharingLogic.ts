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
        saveConfigToState: true,
    }),
    reducers({
        showPreview: [true, { togglePreview: (state) => !state }],
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
                updateState: async (state: Record<string, any>) => {
                    return await api.sharing.update(await propsToApiParams(props), { state })
                },
            },
        ],
    })),
    listeners(({ props }) => ({
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
        setEmbedConfigValue: ({ name, value }, { actions, values }) => {
            if (name === 'whitelabel' && props.dashboardId) {
                eventUsageLogic.actions.reportDashboardWhitelabelToggled(value)
            }
            if (name === 'whitelabel' && props.insightShortId) {
                eventUsageLogic.actions.reportInsightWhitelabelToggled(value)
            }
            // Auto-save all embed config changes to state
            if (values.sharingConfiguration) {
                actions.updateState({
                    ...values.sharingConfiguration.state,
                    [name]: value,
                })
            }
        },
        saveConfigToState: async (_, { values, actions }) => {
            const { embedConfig, sharingConfiguration } = values
            if (sharingConfiguration) {
                // Save all embed config options to state (excluding width/height which are iframe-specific)
                const { width, height, ...stateConfig } = embedConfig
                await actions.updateState({ ...sharingConfiguration.state, ...stateConfig })
            }
        },
        loadSharingConfigurationSuccess: (sharingConfiguration, { actions }) => {
            if (sharingConfiguration && sharingConfiguration.state) {
                // Load all options from state
                actions.setEmbedConfigValues({
                    ...defaultEmbedConfig,
                    ...sharingConfiguration.state,
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
                // Merge all options from state
                ...sharingConfiguration?.state,
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
            (s) => [s.embedLink, s.mergedEmbedConfig],
            (embedLink, { width, height }) => ({
                width,
                height,
                frameBorder: 0,
                allowfullscreen: true,
                src: embedLink,
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

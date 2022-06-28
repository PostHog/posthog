import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { AvailableFeature, InsightShortId, SharingConfigurationType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { getInsightId } from 'scenes/insights/utils'

import type { sharingLogicType } from './sharingLogicType'
import { ExportOptions } from '~/exporter/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { forms } from 'kea-forms'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

export interface SharingLogicProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export interface EmbedConfig extends ExportOptions {
    width: string
    height: string
}

const defaultEmbedConfig: EmbedConfig = {
    width: '100%',
    height: '400',
    whitelabel: false,
    noLegend: false,
}

const propsToApiParams = async (props: SharingLogicProps): Promise<{ dashboardId?: number; insightId?: number }> => {
    const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
    return {
        dashboardId: props.dashboardId,
        insightId,
    }
}

export const sharingLogic = kea<sharingLogicType>([
    path(['lib', 'components', 'Sharing', 'sharingLogic']),
    props({} as SharingLogicProps),
    key(({ insightShortId, dashboardId }) => `sharing-${insightShortId || ''}-${dashboardId || ''}`),
    connect([preflightLogic, userLogic]),

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
            },
        ],
    })),
    forms({
        embedConfig: {
            defaults: defaultEmbedConfig,
        },
    }),
    selectors({
        siteUrl: [() => [preflightLogic.selectors.preflight], (preflight) => preflight?.site_url],
        whitelabelAvailable: [
            () => [userLogic.selectors.user],
            (user) => (user?.organization?.available_features || []).includes(AvailableFeature.WHITE_LABELLING),
        ],
        shareLink: [
            (s) => [s.siteUrl, s.sharingConfiguration, s.embedConfig],
            (siteUrl, sharingConfiguration, { whitelabel, noLegend }) =>
                sharingConfiguration
                    ? siteUrl + urls.shared(sharingConfiguration.access_token, { whitelabel, noLegend })
                    : '',
        ],
        embedLink: [
            (s) => [s.siteUrl, s.sharingConfiguration, s.embedConfig],
            (siteUrl, sharingConfiguration, { whitelabel, noLegend }) =>
                sharingConfiguration
                    ? siteUrl + urls.embedded(sharingConfiguration.access_token, { whitelabel, noLegend })
                    : '',
        ],
        iframeProperties: [
            (s) => [s.embedLink, s.embedConfig],
            (embedLink, { width, height }) => ({
                src: embedLink,
                width,
                height,
                frameborder: 0,
            }),
        ],
        embedCode: [
            (s) => [s.iframeProperties],
            (iframeProperties) =>
                `<iframe ${Object.entries(iframeProperties)
                    .map(([key, value]) => `${key}="${String(value).split('"').join('')}"`)
                    .join(' ')}></iframe>`,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSharingConfiguration()
    }),
])

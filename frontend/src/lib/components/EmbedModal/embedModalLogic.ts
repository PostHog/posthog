import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'

import type { embedModalLogicType } from './embedModalLogicType'
import { InsightShortId } from '~/types'
import { urls } from 'scenes/urls'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { ExportOptions } from '~/exporter/types'

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

export interface EmbedModalLogicProps {
    insightShortId: InsightShortId
}

export const embedModalLogic = kea<embedModalLogicType>([
    path(['lib', 'components', 'EmbedModal', 'embedModalLogic']),
    props({} as EmbedModalLogicProps),
    key((props) => props.insightShortId),
    forms({
        embedConfig: {
            defaults: defaultEmbedConfig,
        },
    }),
    selectors({
        insightShortId: [() => [(_, props) => props.insightShortId], (insightShortId) => insightShortId],
        siteUrl: [() => [preflightLogic.selectors.preflight], (preflight) => preflight?.site_url],
        iframeProperties: [
            (s) => [s.siteUrl, s.embedConfig, s.insightShortId],
            (siteUrl, { width, height, whitelabel, noLegend }, insightShortId) => ({
                src: `${siteUrl}${urls.exportPreview({
                    insight: insightShortId,
                    whitelabel,
                    noLegend,
                })}`,
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
])

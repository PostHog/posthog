import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'

import type { embedModalLogicType } from './embedModalLogicType'
import { InsightShortId } from '~/types'
import { urls } from 'scenes/urls'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export interface EmbedConfig {
    width: string
    height: string
    whitelabel: boolean
}

const defaultEmbedConfig: EmbedConfig = {
    width: '100%',
    height: '400',
    whitelabel: false,
}

interface EmbedModalLogicProps {
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
        embedCode: [
            (s) => [s.siteUrl, s.embedConfig, s.insightShortId],
            (siteUrl, { width, height, whitelabel }, insightShortId) =>
                `<iframe src="${siteUrl}${urls.exportPreview({
                    insight: insightShortId,
                    whitelabel,
                })}" width="${width}" height="${height}" frameborder="0"></iframe>`,
        ],
    }),
])

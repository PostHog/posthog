import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

import type { sitesLogicType } from './sitesLogicType'

export type SiteStat = {
    site: string
    fcp_p90: number | null
    lcp_p90: number | null
    inp_p90: number | null
    cls_p90: number | null
}

export const sitesLogic = kea<sitesLogicType>([
    path(['scenes', 'sites', 'sitesLogic']),
    loaders({
        siteStats: {
            __default: [] as SiteStat[],
            loadSiteStats: async () => {
                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: hogql`select 
                                        -- domainRFC doesn't work for valid domains with no dots e.g. localhost
                                        coalesce(
                                                nullIf(domainRFC(current_url), ''),
                                                extract(current_url, 'https?://([^/]+)')
                                        ) AS domain
    ,round(quantile(0.9)(fcp) as fcp_p90, 2)
    ,round(quantile(0.9)(lcp) as lcp_p90, 2)
    ,round(quantile(0.9)(inp) as inp_p90, 2)
    ,round(quantile(0.9)(cls) as cls_p90, 2)
                                 from web_vitals
                                 where timestamp >=now() - interval 30 day
                                   and timestamp <=now()
                                 group by domain
                                 order by fcp_p90 desc
                                     limit 100`,
                }

                const response = await api.query(query)
                const result = response.results as [string, number, number, number, number][]

                if (result && result.length === 0) {
                    return []
                }

                return result.map((r) => ({
                    site: r[0],
                    fcp_p90: r[1],
                    lcp_p90: r[2],
                    inp_p90: r[3],
                    cls_p90: r[4],
                }))
            },
        },
    }),
    afterMount(({ actions }) => {
        actions.loadSiteStats()
    }),
])

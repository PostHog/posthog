import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DomainScrapeResult } from './types'
import type { vizLogicType } from './vizLogicType'

export const vizLogic = kea<vizLogicType>([
    path(['products', 'ai_visibility', 'frontend', 'vizLogic']),
    actions({
        setDomain: (domain: string) => ({ domain }),
        scrapeDomain: true,
        clearResult: true,
    }),
    reducers({
        domain: [
            '',
            {
                setDomain: (_, { domain }) => domain,
            },
        ],
    }),
    loaders(({ values }) => ({
        scrapeResult: [
            null as DomainScrapeResult | null,
            {
                scrapeDomain: async () => {
                    const response = await api.ai_visibility.scrape({ domain: values.domain })
                    return response
                },
                clearResult: () => null,
            },
        ],
    })),
])

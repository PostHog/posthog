import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { pageReportsLogicType } from './pageReportsLogicType'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export interface PageURL {
    url: string
    count: number
}

export interface PageReportsLogicProps {}

export const pageReportsLogic = kea<pageReportsLogicType>({
    path: ['scenes', 'web-analytics', 'pageReportsLogic'],
    props: {} as PageReportsLogicProps,

    connect: {
        values: [webAnalyticsLogic, ['dateFilter']],
    },

    actions: {
        setPageUrl: (url: string | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadTopPages: true,
        maybeLoadTopPages: true,
    },

    reducers: {
        pageUrl: [
            null as string | null,
            { persist: true },
            {
                setPageUrl: (_, { url }) => url,
            },
        ],
        pageUrlSearchTerm: [
            '',
            {
                setPageUrlSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    },

    loaders: ({ values }) => ({
        topPages: [
            [] as PageURL[],
            {
                loadTopPages: async () => {
                    const query = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`
                            SELECT properties.$pathname AS url, count() as count
                            FROM events
                            WHERE event = '$pageview'
                              AND timestamp >= ${values.dateFilter.dateFrom}
                              AND timestamp <= ${values.dateFilter.dateTo}
                            GROUP BY url
                            ORDER BY count DESC
                            LIMIT 100
                        `,
                    }

                    const res = await api.query(query)
                    return res.results?.map((x: any) => ({ url: x[0], count: x[1] })) as PageURL[]
                },
            },
        ],
        pageUrlSearchResults: [
            [] as string[],
            {
                setPageUrlSearchTerm: async ({ searchTerm }) => {
                    if (!searchTerm) {
                        return []
                    }

                    const query = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`
                            SELECT distinct properties.$pathname AS urls
                            FROM events
                            WHERE event = '$pageview'
                              AND timestamp >= ${values.dateFilter.dateFrom}
                              AND timestamp <= ${values.dateFilter.dateTo}
                              AND properties.$pathname like '%${hogql.identifier(searchTerm)}%'
                            ORDER BY timestamp DESC
                            LIMIT 100
                        `,
                    }

                    const res = await api.query(query)
                    return res.results?.map((x: any) => x[0]) as string[]
                },
            },
        ],
    }),

    selectors: {
        pageUrlSearchOptions: [
            (s) => [s.pageUrlSearchResults, s.topPages, s.pageUrlSearchTerm],
            (pageUrlSearchResults, topPages, pageUrlSearchTerm) => {
                return pageUrlSearchTerm ? pageUrlSearchResults : topPages?.map((x) => x.url) ?? []
            },
        ],
        hasPageUrl: [(s) => [s.pageUrl], (pageUrl) => !!pageUrl],
    },

    listeners: ({ actions, values }) => ({
        maybeLoadTopPages: () => {
            if (!values.topPages.length) {
                actions.loadTopPages()
            }
        },
    }),

    afterMount: ({ actions }) => {
        actions.maybeLoadTopPages()
    },

    urlToAction: ({ actions, values }) => ({
        '/web/page-reports': (_, searchParams) => {
            if (searchParams.pageURL && searchParams.pageURL !== values.pageUrl) {
                actions.setPageUrl(searchParams.pageURL)
            }
        },
    }),

    actionToUrl: ({ values }) => ({
        setPageUrl: () => {
            const searchParams = { ...router.values.searchParams }

            if (values.pageUrl) {
                searchParams.pageURL = values.pageUrl
            } else {
                delete searchParams.pageURL
            }

            return ['/web/page-reports', searchParams, router.values.hashParams, { replace: true }]
        },
    }),
})

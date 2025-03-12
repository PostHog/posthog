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
        values: [webAnalyticsLogic, ['dateFilter', 'isPathCleaningEnabled']],
    },

    actions: {
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => ({ searchTerm }),
    },

    reducers: {
        pageUrl: [
            null as string | null,
            { persist: true },
            {
                setPageUrl: (_state, { url }) => {
                    if (Array.isArray(url)) {
                        return url.length > 0 ? url[0] : null
                    }
                    return url
                },
            },
        ],
        pageUrlSearchTerm: [
            '',
            {
                setPageUrlSearchTerm: (_state, { searchTerm }) => searchTerm,
            },
        ],
        isInitialLoad: [
            true,
            {
                loadPagesSuccess: () => false,
            },
        ],
    },

    loaders: ({ values }) => ({
        pages: [
            [] as PageURL[],
            {
                loadPages: async ({ searchTerm }: { searchTerm: string }) => {
                    // Use path cleaning if enabled
                    const pathCleaningEnabled = values.isPathCleaningEnabled

                    // Create the search pattern
                    const searchPattern = searchTerm ? `%${searchTerm}%` : ''

                    let query

                    if (pathCleaningEnabled) {
                        // Path cleaning enabled query
                        if (searchTerm) {
                            // With search term
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: hogql`
                                    WITH clean_url AS (
                                        replaceRegexpAll(properties.$current_url, '(\\d+)|([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})', '[val]')
                                    )
                                    SELECT clean_url AS url, count() as count
                                    FROM events
                                    WHERE event = '$pageview'
                                      AND timestamp >= ${values.dateFilter.dateFrom}
                                      AND timestamp <= ${values.dateFilter.dateTo}
                                      AND clean_url LIKE ${searchPattern}
                                    GROUP BY url
                                    ORDER BY count DESC
                                `,
                            }
                        } else {
                            // Without search term
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: hogql`
                                    WITH clean_url AS (
                                        replaceRegexpAll(properties.$current_url, '(\\d+)|([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})', '[val]')
                                    )
                                    SELECT clean_url AS url, count() as count
                                    FROM events
                                    WHERE event = '$pageview'
                                      AND timestamp >= ${values.dateFilter.dateFrom}
                                      AND timestamp <= ${values.dateFilter.dateTo}
                                    GROUP BY url
                                    ORDER BY count DESC
                                `,
                            }
                        }
                    } else {
                        // No path cleaning
                        if (searchTerm) {
                            // With search term
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: hogql`
                                    SELECT properties.$current_url AS url, count() as count
                                    FROM events
                                    WHERE event = '$pageview'
                                      AND timestamp >= ${values.dateFilter.dateFrom}
                                      AND timestamp <= ${values.dateFilter.dateTo}
                                      AND properties.$current_url LIKE ${searchPattern}
                                    GROUP BY url
                                    ORDER BY count DESC
                                `,
                            }
                        } else {
                            // Without search term
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: hogql`
                                    SELECT properties.$current_url AS url, count() as count
                                    FROM events
                                    WHERE event = '$pageview'
                                      AND timestamp >= ${values.dateFilter.dateFrom}
                                      AND timestamp <= ${values.dateFilter.dateTo}
                                    GROUP BY url
                                    ORDER BY count DESC
                                `,
                            }
                        }
                    }

                    const response = await api.query(query)
                    const res = response as { results: [string, number][] }
                    return res.results?.map((x) => ({ url: x[0], count: x[1] })) as PageURL[]
                },
            },
        ],
    }),

    selectors: {
        topPages: [
            (selectors) => [selectors.pages, selectors.pageUrlSearchTerm],
            (pages: PageURL[], searchTerm: string): PageURL[] => {
                return searchTerm ? [] : pages
            },
        ],
        pageUrlSearchResults: [
            (selectors) => [selectors.pages, selectors.pageUrlSearchTerm],
            (pages: PageURL[], searchTerm: string): PageURL[] => {
                return searchTerm ? pages : []
            },
        ],
        pageUrlSearchOptions: [
            (selectors) => [selectors.pageUrlSearchResults, selectors.topPages],
            (pageUrlSearchResults: PageURL[], topPages: PageURL[]): string[] => {
                return (pageUrlSearchResults.length > 0 ? pageUrlSearchResults : topPages)?.map((x) => x.url) ?? []
            },
        ],
        pageUrlSearchOptionsWithCount: [
            (selectors) => [selectors.pageUrlSearchResults, selectors.topPages],
            (pageUrlSearchResults: PageURL[], topPages: PageURL[]): PageURL[] => {
                return pageUrlSearchResults.length > 0 ? pageUrlSearchResults : topPages ?? []
            },
        ],
        hasPageUrl: [(selectors) => [selectors.pageUrl], (pageUrl: string | null) => !!pageUrl],
        isLoading: [
            (selectors) => [selectors.pagesLoading, selectors.isInitialLoad],
            (pagesLoading: boolean, isInitialLoad: boolean) => {
                // Make sure we're showing loading state when either pages are loading or it's the initial load
                return pagesLoading || isInitialLoad
            },
        ],
        pageUrlArray: [
            (selectors) => [selectors.pageUrl],
            (pageUrl: string | null): string[] => {
                return pageUrl ? [pageUrl] : []
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setPageUrlSearchTerm: ({ searchTerm }) => {
            actions.loadPages(searchTerm)
        },
        setPageUrl: ({ url }) => {
            // When URL changes, make sure we update the URL in the browser
            // This will trigger the actionToUrl handler
            router.actions.replace('/web/page-reports', url ? { pageURL: url } : {}, router.values.hashParams)
        },
        [webAnalyticsLogic.actionTypes.setDates]: () => {
            actions.loadPages(values.pageUrlSearchTerm)
        },
        [webAnalyticsLogic.actionTypes.setIsPathCleaningEnabled]: () => {
            // Reload pages when path cleaning setting changes
            actions.loadPages(values.pageUrlSearchTerm)
        },
    }),

    afterMount: ({ actions }: { actions: pageReportsLogicType['actions'] }) => {
        // Load pages immediately when component mounts
        actions.loadPages()
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
            // Create a copy of the current search params
            const searchParams = { ...router.values.searchParams }

            // Update the pageURL parameter
            if (values.pageUrl) {
                searchParams.pageURL = values.pageUrl
            } else {
                delete searchParams.pageURL
            }

            // Return the updated URL
            return ['/web/page-reports', searchParams, router.values.hashParams, { replace: true }]
        },
    }),
})

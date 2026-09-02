import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { TileId, WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from './common'
import {
    PagePerformanceMetric,
    buildGoogleSearchConsoleQuery,
    createPagePerformanceInsightProps,
    pagePerformanceLogic,
} from './pagePerformanceLogic'

const GSC_DOCS_URL = 'https://posthog.com/docs/cdp/sources/google-search-console'
const GSC_TABLE_NAME = 'search_analytics_by_query_page'

const MODAL_TITLE: Record<PagePerformanceMetric, string> = {
    llm_referrals: 'LLM referrals',
    agent_crawls: 'Agent crawls',
    google_search: 'Google search',
}

const MODAL_SUBTITLE: Record<PagePerformanceMetric, string> = {
    llm_referrals: 'Human visitors this page received from AI assistants, by referring engine.',
    agent_crawls: 'AI agents that crawled this page. Crawls are excluded from visitor counts.',
    google_search: 'Search queries this page ranks for, from Google Search Console.',
}

const GoogleBreakdown = ({ page, insightProps }: { page: string; insightProps: InsightLogicProps }): JSX.Element => {
    const { dataWarehouseTables, database, databaseLoading, databaseLoadError } = useValues(databaseTableListLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)
    const { currentTeam, isPathCleaningEnabled, window } = useValues(pagePerformanceLogic)

    useOnMountEffect(() => {
        if (!database) {
            loadDatabase()
        }
    })

    const gscTable = dataWarehouseTables.find((t) => t.name.includes(GSC_TABLE_NAME))

    if (!gscTable) {
        if (databaseLoadError) {
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadDatabase({ force: true }) }}
                >
                    Could not load data warehouse tables. Try again to check for your Google Search Console source.
                </LemonBanner>
            )
        }
        if (databaseLoading || !database) {
            return (
                <div className="flex items-center justify-center py-8">
                    <Spinner className="text-2xl" />
                </div>
            )
        }
        return (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
                <p className="text-secondary max-w-md m-0">
                    Google Search Console shows the search queries and average positions each page ranks for. Connect it
                    as a data warehouse source to unlock this breakdown.
                </p>
                <LemonButton type="primary" to={GSC_DOCS_URL} targetBlank sideIcon={<IconOpenInNew />}>
                    Connect Google Search Console
                </LemonButton>
            </div>
        )
    }

    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: buildGoogleSearchConsoleQuery(
                gscTable.name,
                page,
                window,
                isPathCleaningEnabled,
                currentTeam?.path_cleaning_filters
            ),
            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
        },
        embedded: true,
        showActions: false,
    }
    return <Query uniqueKey="page-performance-gsc-breakdown" query={query} readOnly context={{ insightProps }} />
}

export const PagePerformanceBreakdownModal = (): JSX.Element => {
    const { breakdownModal, breakdownQuery } = useValues(pagePerformanceLogic)
    const { closeBreakdown } = useActions(pagePerformanceLogic)

    const isOpen = !!breakdownModal
    const metric = breakdownModal?.metric ?? 'llm_referrals'
    const page = breakdownModal?.page ?? ''
    const insightProps = createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'modal')

    let body: JSX.Element | null = null
    if (metric === 'google_search' && isOpen) {
        body = <GoogleBreakdown page={page} insightProps={insightProps} />
    } else if (breakdownQuery) {
        body = (
            <Query
                uniqueKey={`page-performance-${metric}-breakdown`}
                query={breakdownQuery}
                readOnly
                context={{ insightProps }}
            />
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeBreakdown}
            title={`${MODAL_TITLE[metric]}: ${page || 'this page'}`}
            description={MODAL_SUBTITLE[metric]}
            width={640}
        >
            {metric === 'llm_referrals' && (
                <LemonBanner type="info" className="mb-3">
                    These are people who arrived from an AI assistant, not the assistants' crawlers. Open{' '}
                    <strong>Agent crawls</strong> for the machines reading this page.
                </LemonBanner>
            )}
            {body}
        </LemonModal>
    )
}

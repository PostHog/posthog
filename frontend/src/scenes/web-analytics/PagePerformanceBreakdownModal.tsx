import { useActions, useValues } from 'kea'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { GoogleSearchConsoleKeywords } from 'products/web_analytics/frontend/searchAndAi/GoogleSearchConsoleKeywords'
import { PagePerformanceMetric } from 'products/web_analytics/frontend/searchAndAi/searchAndAiQueries'
import { SearchAndAiQuery } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiQuery'

import { TileId } from './common'
import { createPagePerformanceInsightProps, pagePerformanceLogic } from './pagePerformanceLogic'

const MODAL_TITLE: Record<PagePerformanceMetric, string> = {
    llm_referrals: 'AI referrals',
    agent_crawls: 'AI crawls',
    google_search: 'Google search',
}

const MODAL_SUBTITLE: Record<PagePerformanceMetric, string> = {
    llm_referrals: 'Human visitors this page received from AI assistants, by referring engine.',
    agent_crawls: 'AI agents that crawled this page. Crawls are excluded from visitor counts.',
    google_search: 'Search queries this page ranks for, from Google Search Console.',
}

export const PagePerformanceBreakdownModal = (): JSX.Element => {
    const { breakdownModal, breakdownQuery, currentTeam, isPathCleaningEnabled, window } =
        useValues(pagePerformanceLogic)
    const { closeBreakdown } = useActions(pagePerformanceLogic)

    const isOpen = !!breakdownModal
    const metric = breakdownModal?.metric ?? 'llm_referrals'
    const page = breakdownModal?.page ?? ''
    const insightProps = createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'modal')

    let body: JSX.Element | null = null
    if (metric === 'google_search' && isOpen) {
        body = (
            <GoogleSearchConsoleKeywords
                page={page}
                window={window}
                isPathCleaningEnabled={isPathCleaningEnabled}
                pathCleaningFilters={currentTeam?.path_cleaning_filters}
                insightProps={insightProps}
                uniqueKey="page-performance-gsc-breakdown"
                connectPrompt="text"
            />
        )
    } else if (breakdownQuery) {
        body = (
            <SearchAndAiQuery
                uniqueKey={`page-performance-${metric}-breakdown`}
                query={breakdownQuery}
                insightProps={insightProps}
            />
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeBreakdown}
            title={<span className="break-words">{`${MODAL_TITLE[metric]}: ${page || 'this page'}`}</span>}
            description={MODAL_SUBTITLE[metric]}
            width={640}
        >
            {metric === 'llm_referrals' && (
                <LemonBanner type="info" className="mb-3">
                    These are people who arrived from an AI assistant, not the assistants' crawlers. Open{' '}
                    <strong>AI crawls</strong> for the machines reading this page.
                </LemonBanner>
            )}
            {body}
        </LemonModal>
    )
}

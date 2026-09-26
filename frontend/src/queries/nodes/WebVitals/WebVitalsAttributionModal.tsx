import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { LONG_METRIC_NAME } from './definitions'
import { buildWebVitalsAttributionQuery } from './webVitalsAttribution'

export function WebVitalsAttributionModal({
    path,
    onClose,
}: {
    path: string | null
    onClose: () => void
}): JSX.Element {
    const {
        webVitalsTab,
        webVitalsPercentile,
        dateFilter,
        webAnalyticsFilters,
        filterTestAccounts,
        isPathCleaningEnabled,
        currentTeam,
    } = useValues(webAnalyticsLogic)

    const query = useMemo((): DataTableNode | null => {
        const hogql =
            path !== null &&
            buildWebVitalsAttributionQuery({
                metric: webVitalsTab,
                percentile: webVitalsPercentile,
                path,
                isPathCleaningEnabled,
                pathCleaningFilters: currentTeam?.path_cleaning_filters,
            })
        if (!hogql) {
            return null
        }
        return {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: hogql,
                filters: {
                    properties: webAnalyticsFilters,
                    dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    filterTestAccounts,
                },
                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
            },
            embedded: true,
            showActions: false,
            showOpenEditorButton: true,
        }
    }, [
        path,
        webVitalsTab,
        webVitalsPercentile,
        dateFilter,
        webAnalyticsFilters,
        filterTestAccounts,
        isPathCleaningEnabled,
        currentTeam,
    ])

    const readablePath = path && isPathCleaningEnabled ? parseAliasToReadable(path) : path

    return (
        <LemonModal
            isOpen={path !== null}
            onClose={onClose}
            title={<span className="break-words">{`${LONG_METRIC_NAME[webVitalsTab]}: ${readablePath ?? ''}`}</span>}
            description={`The elements behind ${webVitalsTab} on this page. Timings are the ${webVitalsPercentile} in milliseconds.`}
            width={960}
        >
            {query && <Query query={query} readOnly />}
            <p className="text-xs text-secondary mt-3 mb-0">
                Attribution needs posthog-js 1.419.0 or later. INP and LCP are attributed by default. For CLS, set{' '}
                <code>capture_performance.web_vitals_attribution</code> to <code>true</code>.
            </p>
        </LemonModal>
    )
}

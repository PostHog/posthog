import { BindLogic, BuiltLogic, LogicWrapper, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getCurrencySymbol } from 'lib/utils/currency'
import { InsightEmptyState, InsightErrorState, InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    MARKETING_ANALYTICS_SCHEMA,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsTrendsMetric,
    MarketingAnalyticsTrendsQuery,
    MarketingAnalyticsTrendsQueryResponse,
    TrendsFilter,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { MarketingAnalyticsTrendsChart } from './MarketingAnalyticsTrendsChart'

let uniqueNode = 0

// roas / cost_per_reported_conversion are derived ratios, not part of the raw column schema, so they fall
// through to non-currency formatting — matching the previous TrendsQuery-backed tile behavior.
const isCurrencyMetric = (metric: MarketingAnalyticsTrendsMetric): boolean =>
    MARKETING_ANALYTICS_SCHEMA[metric as unknown as MarketingAnalyticsColumnsSchemaNames]?.isCurrency ?? false

export function MarketingAnalyticsTrends(props: {
    query: MarketingAnalyticsTrendsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
    uniqueKey?: string | number
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [_key] = useState(() => `MarketingAnalyticsTrends.${uniqueNode++}`)
    const key = props.uniqueKey ? String(props.uniqueKey) : _key
    const dataNodeLogicProps = {
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    }

    useAttachedLogic(insightLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(insightVizDataLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), props.attachTo)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <MarketingTrendsTile query={props.query} context={props.context} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function MarketingTrendsTile({
    query,
    context,
}: {
    query: MarketingAnalyticsTrendsQuery
    context: QueryContext
}): JSX.Element {
    const logic = useMountedLogic(dataNodeLogic)
    const { response, responseLoading, responseError, queryId } = useValues(logic)
    const { baseCurrency } = useValues(teamLogic)

    const results = ((response as MarketingAnalyticsTrendsQueryResponse | null)?.results as GraphDataset[]) ?? []

    const { symbol: currencySymbol, isPrefix: currencyIsPrefix } = getCurrencySymbol(baseCurrency)
    const isCurrency = isCurrencyMetric(query.metric)
    const trendsFilter: TrendsFilter = {
        aggregationAxisFormat: 'numeric',
        aggregationAxisPrefix: isCurrency && currencyIsPrefix ? currencySymbol : undefined,
        aggregationAxisPostfix: isCurrency && !currencyIsPrefix ? ` ${currencySymbol}` : undefined,
    }

    let content: JSX.Element
    if (responseLoading) {
        content = <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
    } else if (responseError && results.length === 0) {
        content = <InsightErrorState query={query} queryId={queryId} />
    } else if (results.length === 0) {
        content = <InsightEmptyState heading={context.emptyStateHeading} detail={context.emptyStateDetail} />
    } else {
        content = (
            <MarketingAnalyticsTrendsChart
                dataAttr="marketing-analytics-trends"
                datasets={results.map((result, seriesIndex) => ({ ...result, seriesIndex }))}
                labels={results[0]?.labels ?? []}
                trendsFilter={trendsFilter}
            />
        )
    }

    return (
        <InsightsWrapper>
            <div className="TrendsInsight TrendsInsight--ActionsLineGraph">{content}</div>
        </InsightsWrapper>
    )
}

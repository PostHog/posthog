import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { dataCatalogNewMetricSceneLogic } from '../dataCatalogNewMetricSceneLogic'

export function NewMetricInsightDefinition(): JSX.Element {
    const {
        savedInsights,
        savedInsightsLoading,
        savedInsightsFailed,
        insightSearch,
        selectedInsight,
        metricsUsingSelectedInsight,
    } = useValues(dataCatalogNewMetricSceneLogic)
    const { setInsightSearch, loadSavedInsights } = useActions(dataCatalogNewMetricSceneLogic)

    return (
        <div className="flex flex-col gap-2">
            {savedInsightsFailed && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadSavedInsights(undefined) }}>
                    Couldn't load your saved insights.
                </LemonBanner>
            )}
            <LemonField
                name="sourceInsightShortId"
                help="The metric copies this insight's query. Later insight edits show as drift; they don't update the metric."
            >
                {({ value, onChange }) => (
                    <LemonInputSelect
                        mode="single"
                        value={value ? [value] : []}
                        onChange={(values) => onChange(values[0] || '')}
                        options={savedInsights.map((insight) => ({ key: insight.short_id, label: insight.label }))}
                        loading={savedInsightsLoading}
                        onInputChange={setInsightSearch}
                        placeholder="Search saved insights"
                        emptyStateComponent={
                            <p className="m-0 p-2 text-secondary">
                                {insightSearch ? (
                                    'No insights match this search.'
                                ) : (
                                    <>
                                        No saved insights yet. <Link to={urls.insightNew()}>Create an insight</Link>
                                    </>
                                )}
                            </p>
                        }
                        data-attr="data-catalog-new-metric-insight"
                    />
                )}
            </LemonField>
            {selectedInsight && (
                <div className="flex flex-wrap items-center gap-2 text-sm min-w-0">
                    <span className="font-semibold truncate">{selectedInsight.label}</span>
                    {selectedInsight.typeName && <LemonTag type="muted">{selectedInsight.typeName}</LemonTag>}
                    <Link to={urls.insightView(selectedInsight.short_id as InsightShortId)} target="_blank">
                        Open insight
                    </Link>
                </div>
            )}
            {metricsUsingSelectedInsight.length > 0 && (
                <p className="m-0 text-xs text-secondary">
                    Already used by:{' '}
                    {metricsUsingSelectedInsight.map((name, index) => (
                        <span key={name}>
                            {index > 0 && ', '}
                            <code>{name}</code>
                        </span>
                    ))}
                </p>
            )}
        </div>
    )
}

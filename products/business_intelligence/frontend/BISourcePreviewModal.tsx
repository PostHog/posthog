import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'

import { biSourcePreviewLogic } from './biSourcePreviewLogic'

export function BISourcePreviewModal({ tabId }: { tabId: string }): JSX.Element | null {
    const { worksheet, filtered, limit, query } = useValues(biSourcePreviewLogic({ tabId }))
    const { close, setFiltered, loadMore } = useActions(biSourcePreviewLogic({ tabId }))
    const insightProps = { dashboardItemId: `new-SQL-bi-source-preview-${tabId}` as const }
    const { response, responseLoading } = useValues(
        dataNodeLogic({
            key: insightVizDataNodeKey(insightProps),
            query: query?.source ?? { kind: NodeKind.HogQLQuery, query: '' },
            autoLoad: !!query,
        })
    )
    if (!worksheet) {
        return null
    }
    const rowCount =
        response && 'results' in response && Array.isArray(response.results) ? response.results.length : null
    return (
        <LemonModal title={`Source data: ${worksheet.config.source?.table ?? ''}`} isOpen onClose={close} width="90vw">
            <div className="flex flex-col gap-3">
                <LemonSelect
                    value={filtered}
                    options={[
                        { value: false, label: 'All source rows' },
                        { value: true, label: 'Matching worksheet row and date filters' },
                    ]}
                    onChange={setFiltered}
                    disabledReason={responseLoading ? 'Loading source rows' : undefined}
                    data-attr="bi-source-preview-scope"
                />
                <p className="m-0 text-secondary">
                    Sample of up to <span translate="no">{limit.toLocaleString()}</span> unaggregated rows. Repeated IDs
                    are separate records. A sample does not establish uniqueness. Result filters and table calculations
                    do not apply.
                </p>
                {response && 'types' in response && Array.isArray(response.types) && (
                    <details className="text-xs">
                        <summary className="cursor-pointer">Column names and types</summary>
                        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                            {response.types.map(([name, type]) => (
                                <div key={name} className="flex gap-1">
                                    <dt className="font-semibold">{name}:</dt>
                                    <dd className="m-0 text-secondary">{type}</dd>
                                </div>
                            ))}
                        </dl>
                    </details>
                )}
                {query ? (
                    <div className="flex h-96 min-h-0 flex-col" data-attr="bi-source-preview-table">
                        <Query
                            query={query}
                            context={{ insightProps, dataVisualizationTableVirtualized: true }}
                            readOnly
                            embedded
                        />
                    </div>
                ) : (
                    <LemonBanner type="warning">
                        Check the source and row filters before viewing this sample.
                    </LemonBanner>
                )}
                <LemonButton
                    onClick={loadMore}
                    loading={responseLoading}
                    disabledReason={
                        !query
                            ? 'Choose a valid source and filters'
                            : limit >= 10000
                              ? 'Maximum sample size reached'
                              : rowCount !== null && rowCount < limit
                                ? 'All matching rows are shown'
                                : undefined
                    }
                    data-attr="bi-source-preview-more"
                >
                    Load a larger sample
                </LemonButton>
            </div>
        </LemonModal>
    )
}

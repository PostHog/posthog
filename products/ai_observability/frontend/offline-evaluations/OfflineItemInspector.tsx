import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { OfflineResultReadApi } from '../generated/api.schemas'
import { OfflineItemInspectorLogicProps, offlineItemInspectorLogic } from './offlineItemInspectorLogic'
import { OfflinePayload } from './OfflinePayload'
import { offlineResultLabel } from './offlineResultPresentation'

export function OfflineItemInspector({
    onClose,
    onSelectResult,
    ...props
}: OfflineItemInspectorLogicProps & {
    onClose: () => void
    onSelectResult: (result: OfflineResultReadApi) => void
}): JSX.Element {
    const logic = offlineItemInspectorLogic(props)
    const {
        item,
        itemLoading,
        itemError,
        itemPayload,
        itemPayloadLoading,
        itemPayloadError,
        results,
        resultsLoading,
        resultsError,
        resultCursors,
        selectedResult,
        selectedResultLoading,
        selectedResultError,
        resultPayload,
        resultPayloadLoading,
        resultPayloadError,
    } = useValues(logic)
    const {
        refreshItem,
        loadOfflineItemPayload,
        loadOfflineItemResults,
        nextResults,
        previousResults,
        loadOfflineSelectedResult,
        loadOfflineResultPayload,
    } = useActions(logic)
    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={item?.case_key || item?.dataset_item_identifier || 'Experiment item'}
            width="64rem"
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-4 min-w-0">
                {itemLoading && !item ? (
                    <LemonSkeleton />
                ) : itemError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: refreshItem }}>
                        {itemError}
                    </LemonBanner>
                ) : (
                    item && (
                        <div className="flex flex-wrap items-center gap-2 text-muted text-xs">
                            <span className="font-mono break-all" translate="no">
                                {item.id}
                            </span>
                            {item.trial && <span>{`Trial ${item.trial}`}</span>}
                            {item.application_trace_id && (
                                <Link to={urls.aiObservabilityTrace(item.application_trace_id)}>Application trace</Link>
                            )}
                        </div>
                    )
                )}
                <section>
                    <h3>Input and output</h3>
                    {itemPayloadLoading ? (
                        <LemonSkeleton />
                    ) : itemPayloadError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => loadOfflineItemPayload() }}
                        >
                            {itemPayloadError}
                        </LemonBanner>
                    ) : (
                        itemPayload && (
                            <OfflinePayload
                                payload={itemPayload}
                                fields={['input', 'output', 'expected_output', 'metadata']}
                            />
                        )
                    )}
                </section>
                <section>
                    <h3>Scores</h3>
                    {resultsError && (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => loadOfflineItemResults() }}
                        >
                            {resultsError}
                        </LemonBanner>
                    )}
                    <LemonTable
                        dataSource={resultsError ? [] : results?.results || []}
                        loading={resultsLoading}
                        rowKey="id"
                        size="small"
                        emptyState={
                            resultsError ? 'Results are unavailable.' : 'No results were submitted for this item.'
                        }
                        columns={[
                            {
                                title: 'Scorer',
                                render: (_, result: OfflineResultReadApi) => (
                                    <LemonButton
                                        type="tertiary"
                                        size="small"
                                        onClick={() => onSelectResult(result)}
                                    >{`${result.scorer.name} v${result.scorer.version}`}</LemonButton>
                                ),
                            },
                            {
                                title: 'Score',
                                render: (_, result: OfflineResultReadApi) => (
                                    <span
                                        className={
                                            result.status === 'error'
                                                ? 'text-danger'
                                                : result.status === 'ok'
                                                  ? undefined
                                                  : 'text-muted'
                                        }
                                        translate="no"
                                    >
                                        {offlineResultLabel(result, result.scorer)}
                                    </span>
                                ),
                            },
                        ]}
                    />
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs text-muted">
                            {resultsError
                                ? 'Results are unavailable. Retry or return to the previous page.'
                                : resultsLoading
                                  ? 'Loading results…'
                                  : results
                                    ? `${results.results.length} of ${results.count} results`
                                    : 'Loading results…'}
                        </span>
                        <div className="flex gap-2">
                            <LemonButton
                                size="small"
                                disabled={!resultCursors.length || resultsLoading}
                                onClick={previousResults}
                            >
                                Previous
                            </LemonButton>
                            <LemonButton
                                size="small"
                                disabled={!!resultsError || !results?.next_cursor || resultsLoading}
                                onClick={() => results?.next_cursor && nextResults(results.next_cursor)}
                            >
                                Next
                            </LemonButton>
                        </div>
                    </div>
                </section>
                {(props.resultId || selectedResult) && (
                    <section>
                        <h3>Result details</h3>
                        {selectedResultLoading ? (
                            <LemonSkeleton />
                        ) : selectedResultError ? (
                            <LemonBanner
                                type="error"
                                action={{ children: 'Try again', onClick: () => loadOfflineSelectedResult() }}
                            >
                                {selectedResultError}
                            </LemonBanner>
                        ) : (
                            selectedResult && (
                                <div className="flex flex-col gap-3">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <strong>{`${selectedResult.scorer.name} v${selectedResult.scorer.version}`}</strong>
                                        <span
                                            className={
                                                selectedResult.status === 'error'
                                                    ? 'text-danger'
                                                    : selectedResult.status === 'ok'
                                                      ? undefined
                                                      : 'text-muted'
                                            }
                                            translate="no"
                                        >
                                            {offlineResultLabel(selectedResult, selectedResult.scorer)}
                                        </span>
                                    </div>
                                    {selectedResult.status === 'ok' && (
                                        <div className="text-xs">
                                            <span>Raw value: </span>
                                            <code translate="no" className="break-all">
                                                {JSON.stringify(selectedResult.value)}
                                            </code>
                                        </div>
                                    )}
                                    {selectedResult.error_code && (
                                        <LemonBanner type="warning">{`Evaluator error: ${selectedResult.error_code}`}</LemonBanner>
                                    )}
                                    <div className="text-xs text-muted flex flex-wrap gap-2">
                                        <span>Accepted</span>
                                        <TZLabel time={selectedResult.accepted_at} />
                                        {selectedResult.evaluator_trace_id && (
                                            <Link to={urls.aiObservabilityTrace(selectedResult.evaluator_trace_id)}>
                                                Evaluator trace
                                            </Link>
                                        )}
                                    </div>
                                    {resultPayloadLoading ? (
                                        <LemonSkeleton />
                                    ) : resultPayloadError ? (
                                        <LemonBanner
                                            type="error"
                                            action={{
                                                children: 'Try again',
                                                onClick: () => loadOfflineResultPayload(),
                                            }}
                                        >
                                            {resultPayloadError}
                                        </LemonBanner>
                                    ) : (
                                        resultPayload?.id === selectedResult.id && (
                                            <OfflinePayload
                                                payload={resultPayload}
                                                fields={['reasoning', 'error_message', 'metadata']}
                                            />
                                        )
                                    )}
                                </div>
                            )
                        )}
                    </section>
                )}
            </div>
        </LemonModal>
    )
}

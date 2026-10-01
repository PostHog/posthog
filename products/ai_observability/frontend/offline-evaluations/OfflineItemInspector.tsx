import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonModal,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
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
        <LemonModal isOpen onClose={onClose} width="64rem" simple>
            <LemonModalHeader>
                <h3 className="break-words pr-8">
                    {item?.case_key || item?.dataset_item_identifier || 'Experiment item'}
                </h3>
            </LemonModalHeader>
            <LemonModalContent className="bg-surface-secondary">
                <div className="flex flex-col gap-6 min-w-0">
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
                                    <Link to={urls.aiObservabilityTrace(item.application_trace_id)}>
                                        Application trace
                                    </Link>
                                )}
                            </div>
                        )
                    )}
                    {(props.resultId || selectedResult) && (
                        <section aria-label="Result details" className="min-w-0">
                            <h3 className="text-base mb-3">Result details</h3>
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
                                        <LemonCard hoverEffect={false} className="p-4 space-y-3">
                                            <div className="flex flex-wrap items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="font-semibold break-words">
                                                        {selectedResult.scorer.name}
                                                    </div>
                                                    <span className="text-xs text-muted">{`Version ${selectedResult.scorer.version}`}</span>
                                                </div>
                                                <LemonTag
                                                    type={selectedResult.status === 'error' ? 'danger' : 'default'}
                                                    size="medium"
                                                    wrap
                                                >
                                                    <span className="text-lg font-semibold break-words" translate="no">
                                                        {offlineResultLabel(selectedResult, selectedResult.scorer)}
                                                    </span>
                                                </LemonTag>
                                            </div>
                                            {selectedResult.error_code && (
                                                <LemonBanner type="warning">{`Evaluator error: ${selectedResult.error_code}`}</LemonBanner>
                                            )}
                                            <details className="text-xs border-t pt-3">
                                                <summary className="cursor-pointer font-medium">
                                                    Result metadata
                                                </summary>
                                                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-muted">
                                                    {selectedResult.status === 'ok' && (
                                                        <span>
                                                            Raw value:{' '}
                                                            <code translate="no" className="break-all">
                                                                {JSON.stringify(selectedResult.value)}
                                                            </code>
                                                        </span>
                                                    )}
                                                    <span className="flex items-center gap-1">
                                                        <span>Accepted</span>
                                                        <TZLabel time={selectedResult.accepted_at} />
                                                    </span>
                                                    {selectedResult.evaluator_trace_id && (
                                                        <Link
                                                            to={urls.aiObservabilityTrace(
                                                                selectedResult.evaluator_trace_id
                                                            )}
                                                        >
                                                            Evaluator trace
                                                        </Link>
                                                    )}
                                                </div>
                                            </details>
                                        </LemonCard>
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
                    <section aria-label="Input and output" className="min-w-0">
                        <h3 className="text-base mb-3">Input and output</h3>
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
                    <section aria-label="Scores" className="min-w-0">
                        <h3 className="text-base mb-3">Scores</h3>
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
                                            noPadding
                                            className="max-w-full"
                                            active={result.id === selectedResult?.id}
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
                </div>
            </LemonModalContent>
            <LemonModalFooter>
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}

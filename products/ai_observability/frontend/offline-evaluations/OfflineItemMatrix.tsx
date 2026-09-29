import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { OfflineItemReadApi } from '../generated/api.schemas'
import { OfflineExperimentLogicProps, offlineExperimentLogic } from './offlineExperimentLogic'
import { offlineResultLabel } from './offlineResultPresentation'

export function OfflineItemMatrix(props: OfflineExperimentLogicProps): JSX.Element {
    const logic = offlineExperimentLogic(props)
    const {
        items,
        itemsLoading,
        itemsError,
        itemCursors,
        scorers,
        cellBatches,
        cellsByItemAndVersion,
        focusedScorerVersionId,
        summaryCountLoading,
        summariesError,
    } = useValues(logic)
    const { loadOfflineItems, nextItems, previousItems, openItem, setViewport, retryCellBatch } = useActions(logic)
    const tableRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (focusedScorerVersionId) {
            const header = Array.from(
                tableRef.current?.querySelectorAll<HTMLElement>('[data-offline-scorer]') || []
            ).find((element) => element.dataset.offlineScorer === focusedScorerVersionId)
            header?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        }
    }, [focusedScorerVersionId, scorers.length])
    const columns: LemonTableColumns<OfflineItemReadApi> = [
        {
            title: 'Item',
            key: 'item',
            width: 220,
            className: 'min-w-[220px] max-w-[220px]',
            render: (_, item) => (
                <div className="min-w-0 flex flex-col items-start gap-1">
                    <LemonButton
                        data-attr="offline-experiment-open-item"
                        noPadding
                        size="small"
                        type="tertiary"
                        className="max-w-full !my-0"
                        onClick={() => openItem(item.id)}
                    >
                        <span className="truncate" title={item.id}>
                            {item.case_key || item.dataset_item_identifier || item.id.slice(0, 8)}
                        </span>
                    </LemonButton>
                    <div className="text-xs text-muted truncate max-w-full">
                        {[
                            item.trial ? `Trial ${item.trial}` : null,
                            item.payload_state === 'available'
                                ? 'Payload available'
                                : item.payload_state === 'expired'
                                  ? 'Payload expired'
                                  : 'No payload',
                        ]
                            .filter(Boolean)
                            .join(' · ')}
                    </div>
                </div>
            ),
        },
        ...scorers.map((scorer, index) => ({
            key: scorer.id,
            width: 180,
            className: 'min-w-[180px] max-w-[180px]',
            title: (
                <span
                    data-offline-scorer={scorer.id}
                    className="block truncate"
                    title={`${scorer.name} v${scorer.version}`}
                >{`${scorer.name} v${scorer.version}`}</span>
            ),
            render: (_: unknown, item: OfflineItemReadApi) => {
                const batchIndex = Math.floor(index / 20)
                const batch = cellBatches[batchIndex]
                if (batch?.state === 'error') {
                    return (
                        <LemonButton
                            size="xsmall"
                            data-attr="offline-experiment-retry-scores"
                            status="danger"
                            onClick={() => retryCellBatch(batchIndex)}
                            tooltip={batch.error}
                        >
                            Retry scores
                        </LemonButton>
                    )
                }
                if (batch?.state !== 'loaded') {
                    return (
                        <span className="text-muted text-xs">
                            {batch?.state === 'loading' ? 'Loading…' : 'Scroll to load'}
                        </span>
                    )
                }
                const result = cellsByItemAndVersion[`${item.id}:${scorer.id}`]
                return result ? (
                    <LemonButton
                        size="small"
                        type="tertiary"
                        data-attr="offline-experiment-open-result"
                        onClick={() => openItem(item.id, result.id, scorer.id)}
                        fullWidth
                        className="justify-start"
                        tooltip={result.error_code || undefined}
                    >
                        <span
                            className={
                                result.status === 'error'
                                    ? 'truncate text-danger'
                                    : result.status === 'ok'
                                      ? 'truncate'
                                      : 'truncate text-muted'
                            }
                            translate="no"
                        >
                            {offlineResultLabel(result, scorer)}
                        </span>
                    </LemonButton>
                ) : (
                    <span className="text-muted text-xs">No result</span>
                )
            },
        })),
    ]
    return (
        <section className="min-w-0">
            <div className="mb-2">
                <h3 className="mb-0">Items</h3>
                <p className="text-xs text-muted mb-0">
                    {summaryCountLoading
                        ? 'Discovering all scorer columns…'
                        : summariesError
                          ? 'Some scorer columns could not be loaded.'
                          : 'All scorers are shown. Scroll horizontally to inspect more scores.'}
                </p>
            </div>
            {itemsError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadOfflineItems() }}>
                    {itemsError}
                </LemonBanner>
            )}
            {focusedScorerVersionId &&
                !summaryCountLoading &&
                !summariesError &&
                !scorers.some((scorer) => scorer.id === focusedScorerVersionId) && (
                    <LemonBanner type="info">
                        No visible results were submitted for the requested scorer version.
                    </LemonBanner>
                )}
            <div
                ref={tableRef}
                className="min-w-0"
                onScrollCapture={(event) => {
                    const target = event.target as HTMLElement
                    if (target.scrollWidth > target.clientWidth) {
                        setViewport(target.scrollLeft, target.clientWidth)
                    }
                }}
            >
                <LemonTable
                    dataSource={itemsError ? [] : items?.results || []}
                    columns={columns}
                    loading={itemsLoading}
                    rowKey="id"
                    size="small"
                    firstColumnSticky
                    emptyState={itemsError ? 'Items are unavailable.' : 'No items have been uploaded yet.'}
                />
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted">
                    {itemsError
                        ? 'Items are unavailable. Retry or return to the previous page.'
                        : itemsLoading
                          ? 'Loading items…'
                          : items
                            ? `${items.results.length} of ${items.count} items · Page ${itemCursors.length + 1}`
                            : 'Loading items…'}
                </span>
                <div className="flex gap-2">
                    <LemonButton size="small" disabled={!itemCursors.length || itemsLoading} onClick={previousItems}>
                        Previous
                    </LemonButton>
                    <LemonButton
                        size="small"
                        disabled={!!itemsError || !items?.next_cursor || itemsLoading}
                        onClick={() => items?.next_cursor && nextItems(items.next_cursor)}
                    >
                        Next
                    </LemonButton>
                </div>
            </div>
        </section>
    )
}

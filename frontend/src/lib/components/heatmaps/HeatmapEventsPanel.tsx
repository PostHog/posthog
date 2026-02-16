import { useActions, useValues } from 'kea'

import { HeatmapDataLogicProps, heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapEvent } from 'lib/components/heatmaps/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

export function HeatmapEventsPanel({ context, exportToken }: HeatmapDataLogicProps): JSX.Element | null {
    const { showEventsPanel, areaEvents, areaEventsLoading, areaEventsLoadingMore } = useValues(
        heatmapDataLogic({ context, exportToken })
    )
    const { setShowEventsPanel, clearSelectedArea, loadMoreAreaEvents } = useActions(
        heatmapDataLogic({ context, exportToken })
    )

    if (!showEventsPanel) {
        return null
    }

    const handleClose = (): void => {
        setShowEventsPanel(false)
        clearSelectedArea()
    }

    const columns: LemonTableColumns<HeatmapEvent> = [
        {
            title: 'Time',
            dataIndex: 'timestamp',
            sorter: (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
            render: (_, event) => humanFriendlyDetailedTime(event.timestamp),
        },
        {
            title: 'Type',
            dataIndex: 'type',
            sorter: (a, b) => a.type.localeCompare(b.type),
        },
        {
            title: 'User',
            dataIndex: 'distinct_id',
            sorter: (a, b) => a.distinct_id.localeCompare(b.distinct_id),
            render: (_, event) => <PersonDisplay person={{ distinct_id: event.distinct_id }} noPopover />,
        },
        {
            title: '',
            render: (_, event) =>
                event.session_id ? (
                    <LemonButton size="xsmall" to={urls.sessionProfile(event.session_id)} targetBlank>
                        View session
                    </LemonButton>
                ) : null,
        },
    ]

    return (
        <LemonModal title="Events in this area" onClose={handleClose} isOpen width={700}>
            {areaEventsLoading ? (
                <div className="space-y-2 p-4">
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-8 w-full" />
                </div>
            ) : areaEvents?.results && areaEvents.results.length > 0 ? (
                <>
                    <div className="px-4 py-2 border-b text-sm text-muted">
                        <div>
                            {areaEvents.total_count} event{areaEvents.total_count !== 1 ? 's' : ''} found
                            {areaEvents.has_more && ` (showing ${areaEvents.results.length})`}
                        </div>
                        <div className="text-xs mt-1">
                            Note: These are raw events at this exact coordinate. The heatmap display uses interpolation,
                            so the count shown on hover may differ.
                        </div>
                    </div>
                    <LemonTable
                        dataSource={areaEvents.results}
                        columns={columns}
                        size="small"
                        rowKey={(record) => `${record.timestamp}-${record.distinct_id}`}
                        className="max-h-[400px] overflow-auto"
                    />
                    {areaEvents.has_more && (
                        <div className="flex justify-center p-4 border-t">
                            <LemonButton
                                type="secondary"
                                onClick={() => loadMoreAreaEvents()}
                                loading={areaEventsLoadingMore}
                            >
                                Load more events
                            </LemonButton>
                        </div>
                    )}
                </>
            ) : (
                <div className="p-8 text-center text-muted">No events found in this area</div>
            )}
        </LemonModal>
    )
}

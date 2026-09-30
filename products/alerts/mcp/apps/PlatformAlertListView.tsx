import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { type PlatformAlertData, PlatformAlertView, nextCheckLabel, summarizePlatformAlert } from './PlatformAlertView'

export interface PlatformAlertListData {
    results: PlatformAlertData[]
    _posthogUrl?: string
}

export interface PlatformAlertListViewProps {
    data: PlatformAlertListData
    onPlatformAlertClick?: (alert: PlatformAlertData) => Promise<PlatformAlertData | null>
}

function groupsLabel(alert: PlatformAlertData): string {
    if (alert.alerts.length <= 1) {
        return 'Ungrouped'
    }
    return `${alert.alerts.length} groups`
}

export function PlatformAlertListView({ data, onPlatformAlertClick }: PlatformAlertListViewProps): ReactElement {
    const firingCount = data.results.filter(
        (alert) => alert.enabled && alert.alerts.some((group) => group.state === 'firing')
    ).length

    return (
        <ListDetailView<PlatformAlertData>
            onItemClick={onPlatformAlertClick}
            backLabel="All platform alerts"
            getItemName={(alert) => alert.name}
            renderDetail={(alert) => <PlatformAlertView data={alert} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<PlatformAlertData>[] = [
                    {
                        key: 'name',
                        header: 'Alert',
                        sortable: true,
                        render: (row): ReactNode => (
                            <div className="flex flex-col">
                                {onPlatformAlertClick ? (
                                    <Button
                                        variant="link"
                                        size="sm"
                                        onClick={() => handleClick(row)}
                                        className="h-auto px-0 text-left max-w-xs truncate"
                                    >
                                        {row.name}
                                    </Button>
                                ) : (
                                    <span className="max-w-xs truncate block font-medium">{row.name}</span>
                                )}
                                <span className="text-xs text-muted-foreground">
                                    {row.source_kind}, every {row.check_interval_minutes} min
                                </span>
                            </div>
                        ),
                    },
                    {
                        key: 'state',
                        header: 'State',
                        render: (row): ReactNode => summarizePlatformAlert(row),
                    },
                    {
                        key: 'groups',
                        header: 'Groups',
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground text-xs">{groupsLabel(row)}</span>
                        ),
                    },
                    {
                        key: 'next_check_at',
                        header: 'Next check',
                        sortable: true,
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground text-xs">{nextCheckLabel(row)}</span>
                        ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-sm text-muted-foreground">
                                    {data.results.length} alert{data.results.length === 1 ? '' : 's'}
                                </span>
                                {firingCount > 0 && <Badge variant="destructive">{firingCount} firing</Badge>}
                            </div>
                            <DataTable<PlatformAlertData>
                                columns={columns}
                                data={data.results}
                                pageSize={20}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No platform alerts in this project yet"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}

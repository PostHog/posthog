import { useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'

import {
    downloadExport,
    getFilterSummary,
    getFilterTooltip,
    getHumanReadableFormat,
    getStatusTag,
} from './ExportsListHelpers'
import { ExportedAsset, advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export function ExportsList(): JSX.Element {
    const { exports, exportsLoading } = useValues(advancedActivityLogsLogic)

    const columns = [
        {
            title: 'Filename',
            dataIndex: 'filename' as keyof ExportedAsset,
            key: 'filename',
            render: (filename: any) => (filename ? String(filename) : 'export'),
        },
        {
            title: 'Format',
            dataIndex: 'export_format' as keyof ExportedAsset,
            key: 'export_format',
            render: (format: any) => (format ? getHumanReadableFormat(String(format)) : ''),
        },
        {
            title: 'Filters',
            key: 'filters',
            render: (_: any, exportAsset: ExportedAsset) => (
                <Tooltip title={getFilterTooltip(exportAsset)}>
                    <span className="text-muted text-xs cursor-help">{getFilterSummary(exportAsset)}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_: any, exportAsset: ExportedAsset) => getStatusTag(exportAsset),
        },
        {
            title: 'Created',
            dataIndex: 'created_at' as keyof ExportedAsset,
            key: 'created_at',
            render: (createdAt: any) => (createdAt ? humanFriendlyDetailedTime(String(createdAt)) : ''),
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, exportAsset: ExportedAsset) => {
                const failedReason = exportAsset.exception && 'Failed to export'
                const disabledReason = !exportAsset.has_content && 'Export is not ready'

                return (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconDownload />}
                        disabledReason={failedReason || disabledReason}
                        onClick={() => downloadExport(exportAsset)}
                        data-attr={`audit-logs-download-export-${exportAsset.id}`}
                    >
                        Download
                    </LemonButton>
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Your exports</h3>
                <p className="text-muted text-xs">Refreshed every 5 seconds</p>
            </div>

            <LemonTable
                dataSource={exports || []}
                columns={columns}
                loading={exportsLoading}
                rowKey="id"
                emptyState="No exports found"
            />
        </div>
    )
}

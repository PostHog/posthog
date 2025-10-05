import { useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { DetectiveHog } from 'lib/components/hedgehogs'
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

    if (!exports || exports.length === 0) {
        return <ExportsEmptyState />
    }

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
                    <div className="text-muted text-xs cursor-help truncate max-w-48">
                        {getFilterSummary(exportAsset)}
                    </div>
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
            <LemonTable
                dataSource={exports}
                columns={columns}
                loading={exportsLoading}
                rowKey="id"
                footer={
                    <div className="flex items-center justify-end mt-2 mr-2">
                        <p className="text-muted text-xs">Refreshed every 5 seconds</p>
                    </div>
                }
            />
        </div>
    )
}

const ExportsEmptyState = (): JSX.Element => (
    <div
        data-attr="exports-empty-state"
        className="flex flex-col border rounded px-4 py-8 items-center text-center mx-auto"
    >
        <DetectiveHog width="100" height="100" className="mb-4" />
        <h2 className="text-xl leading-tight">No exports found</h2>
        <p className="text-sm text-balance text-tertiary">
            Exports will appear here when you create them from the Logs tab. Start by applying filters and then click
            "Export".
        </p>
    </div>
)

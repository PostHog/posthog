import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconExport } from 'lib/components/icons'
import { Popconfirm } from 'antd'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import api from 'lib/api'
import { DataTableNode } from '~/queries/schema'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/DataTable'

function startDownload(query: DataTableNode, onlySelectedColumns: boolean): void {
    const exportContext = {
        path: api.events.determineListEndpoint({
            event: query.source.event,
            properties: query.source.properties,
            limit: query.source.limit,
        }),
        max_limit: 3500,
    }
    if (onlySelectedColumns) {
        exportContext['columns'] = query.columns ?? defaultDataTableStringColumns
    }
    triggerExport({
        export_format: ExporterFormat.CSV,
        export_context: exportContext,
    })
}

interface DataTableExportProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

export function DataTableExport({ query }: DataTableExportProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            popup={{
                sameWidth: false,
                closeOnClickInside: false,
                overlay: [
                    <ExportWithConfirmation
                        key={1}
                        placement={'topRight'}
                        onConfirm={() => {
                            startDownload(query, true)
                        }}
                    >
                        <LemonButton fullWidth={true} status="stealth">
                            Export current columns
                        </LemonButton>
                    </ExportWithConfirmation>,
                    <ExportWithConfirmation
                        key={0}
                        placement={'bottomRight'}
                        onConfirm={() => startDownload(query, false)}
                    >
                        <LemonButton fullWidth={true} status="stealth">
                            Export all columns
                        </LemonButton>
                    </ExportWithConfirmation>,
                ],
            }}
            type="secondary"
            icon={<IconExport />}
        >
            Export
        </LemonButtonWithPopup>
    )
}

interface ExportWithConfirmationProps {
    placement: 'topRight' | 'bottomRight'
    onConfirm: (e?: React.MouseEvent<HTMLElement>) => void
    children: React.ReactNode
}

function ExportWithConfirmation({ placement, onConfirm, children }: ExportWithConfirmationProps): JSX.Element {
    return (
        <Popconfirm
            placement={placement}
            title={
                <>
                    Exporting by csv is limited to 3,500 events.
                    <br />
                    To return more, please use <a href="https://posthog.com/docs/api/events">the API</a>. Do you want to
                    export by CSV?
                </>
            }
            onConfirm={onConfirm}
        >
            {children}
        </Popconfirm>
    )
}

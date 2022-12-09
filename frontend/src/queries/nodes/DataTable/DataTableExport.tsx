import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconExport } from 'lib/components/icons'
import { Popconfirm } from 'antd'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import { DataTableNode } from '~/queries/schema'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/defaults'
import { isEventsNode, isPersonsNode } from '~/queries/utils'
import { getEventsEndpoint, getPersonsEndpoint } from '~/queries/query'

const DEFAULT_EXPORT_LIMIT = 3500

function startDownload(query: DataTableNode, onlySelectedColumns: boolean): void {
    const exportContext = isEventsNode(query.source)
        ? {
              path: getEventsEndpoint({ ...query.source, limit: DEFAULT_EXPORT_LIMIT }),
              max_limit: query.source.limit ?? DEFAULT_EXPORT_LIMIT,
          }
        : isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source), max_limit: DEFAULT_EXPORT_LIMIT }
        : undefined
    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    const columnMapping = {
        url: ['properties.$current_url', 'properties.$screen_name'],
        time: 'timestamp',
        event: 'event',
        source: 'properties.$lib',
        person: isPersonsNode(query.source)
            ? ['distinct_ids.0', 'properties.email']
            : ['person.distinct_ids.0', 'person.properties.email'],
    }

    if (onlySelectedColumns) {
        exportContext['columns'] = (query.columns ?? defaultDataTableColumns(query.source))
            ?.flatMap((c) => columnMapping[c] || c)
            .filter((c) => c !== 'person.$delete')
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

export function DataTableExport({ query }: DataTableExportProps): JSX.Element | null {
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
                        <LemonButton fullWidth status="stealth">
                            Export current columns
                        </LemonButton>
                    </ExportWithConfirmation>,
                    <ExportWithConfirmation
                        key={0}
                        placement={'bottomRight'}
                        onConfirm={() => startDownload(query, false)}
                    >
                        <LemonButton fullWidth status="stealth">
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

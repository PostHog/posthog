import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconExport } from 'lib/lemon-ui/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import { DataNode, DataTableNode } from '~/queries/schema'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { isEventsQuery, isPersonsNode } from '~/queries/utils'
import { getEventsEndpoint, getPersonsEndpoint } from '~/queries/query'
import { ExportWithConfirmation } from '~/queries/nodes/DataTable/ExportWithConfirmation'

const EXPORT_LIMIT_EVENTS = 3500
const EXPORT_LIMIT_PERSONS = 10000

function startDownload(query: DataTableNode, onlySelectedColumns: boolean): void {
    const exportContext = isEventsQuery(query.source)
        ? {
              path: getEventsEndpoint({ ...query.source, limit: EXPORT_LIMIT_EVENTS }),
              max_limit: query.source.limit ?? EXPORT_LIMIT_EVENTS,
          }
        : isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source), max_limit: EXPORT_LIMIT_PERSONS }
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
        exportContext['columns'] = (query.columns ?? defaultDataTableColumns(query.source.kind))
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
    setQuery?: (query: DataTableNode) => void
}

export function DataTableExport({ query }: DataTableExportProps): JSX.Element | null {
    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)

    return (
        <LemonButtonWithDropdown
            dropdown={{
                sameWidth: false,
                closeOnClickInside: false,
                overlay: [
                    <ExportWithConfirmation
                        key={1}
                        placement={'topRight'}
                        onConfirm={() => {
                            startDownload(query, true)
                        }}
                        actor={isPersonsNode(query.source) ? 'persons' : 'events'}
                        limit={isPersonsNode(query.source) ? EXPORT_LIMIT_PERSONS : EXPORT_LIMIT_EVENTS}
                    >
                        <LemonButton fullWidth status="stealth">
                            Export current columns
                        </LemonButton>
                    </ExportWithConfirmation>,
                    <ExportWithConfirmation
                        key={0}
                        placement={'bottomRight'}
                        onConfirm={() => startDownload(query, false)}
                        actor={isPersonsNode(query.source) ? 'persons' : 'events'}
                        limit={isPersonsNode(query.source) ? EXPORT_LIMIT_PERSONS : EXPORT_LIMIT_EVENTS}
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
            Export{filterCount > 0 ? ` (${filterCount} filter${filterCount === 1 ? '' : 's'})` : ''}
        </LemonButtonWithDropdown>
    )
}

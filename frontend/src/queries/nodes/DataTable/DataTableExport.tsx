import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { ExportColumnsModal, TABULAR_EXPORT_FORMATS } from 'lib/components/ExportButton/ExportColumnsModal'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { SaveToCohortModalContent } from 'lib/components/SaveToCohortModalContent/SaveToCohortModalContent'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import {
    copyTableToCsv,
    copyTableToExcel,
    copyTableToJson,
    projectExportRows,
} from '~/queries/nodes/DataTable/clipboardUtils'
import {
    shouldOptimizeForExport,
    transformColumnsForExport,
    transformQuerySourceForExport,
} from '~/queries/nodes/DataTable/exportTransformers'
import { defaultDataTableColumns, extractDisplayLabel, removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { DataNode, DataTableNode } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isGroupsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
    isSessionsQuery,
} from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, ExportContext, ExporterFormat } from '~/types'

import { dataTableLogic } from './dataTableLogic'

// Sync with posthog/hogql/constants.py
export const MAX_SELECT_RETURNED_ROWS = 50000

const columnDisallowList = ['person.$delete', '*']

function personDisplayNameProperties(): string[] {
    return (
        teamLogic.findMounted()?.values?.currentTeam?.person_display_name_properties ??
        PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    )
}

// The names the export produces for the table's current columns, which is also what the column
// picker offers.
export function exportColumnsForQuery(query: DataTableNode): string[] {
    const shouldOptimize = shouldOptimizeForExport(query)

    let columns = (
        (isEventsQuery(query.source) ||
        isActorsQuery(query.source) ||
        isGroupsQuery(query.source) ||
        isSessionsQuery(query.source)
            ? query.source.select
            : null) ??
        query.columns ??
        defaultDataTableColumns(query.source.kind)
    )?.filter((c) => c !== 'person.$delete')

    // Apply export optimizations to columns
    if (shouldOptimize && isEventsQuery(query.source)) {
        columns = transformColumnsForExport(columns, personDisplayNameProperties())
    } else if (isPersonsNode(query.source)) {
        columns = columns.map((c: string) => (removeExpressionComment(c) === 'person' ? 'email' : c))
    }

    if (columns.includes('person')) {
        // Expand the `person` column to `person.id` (canonical UUID, always populated),
        // `person.distinct_ids.0` (may be blank when the person can't be hydrated), and
        // `person.is_unresolved` (true for merged/deleted persons whose Postgres row is
        // missing). The id keeps every row identifiable; is_unresolved must be listed
        // explicitly so the backend's user_columns filter doesn't drop it.
        columns = columns.flatMap((c: string) =>
            c === 'person' ? ['person.id', 'person.distinct_ids.0', 'person.is_unresolved'] : [c]
        )
    }

    return columns.filter((n: string) => !columnDisallowList.includes(n))
}

export async function startDownload(
    query: DataTableNode,
    onlySelectedColumns: boolean,
    exportCall: (exportData: TriggerExportProps) => void,
    format: ExporterFormat = ExporterFormat.CSV,
    fileNameForExport?: string,
    selectedColumns?: string[]
): Promise<void> {
    const shouldOptimize = shouldOptimizeForExport(query)

    let exportSource = query.source

    // Remove person column from the source otherwise export fails when there's 1000+ records
    if (shouldOptimize && isEventsQuery(query.source)) {
        exportSource = transformQuerySourceForExport(query.source, personDisplayNameProperties())
    }

    const exportContext: ExportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source) }
        : { source: exportSource }

    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    const columns = selectedColumns ?? (onlySelectedColumns ? exportColumnsForQuery(query) : null)
    if (columns) {
        exportContext['columns'] = columns
    }
    if (fileNameForExport != null) {
        exportContext['filename'] = fileNameForExport
    }
    exportCall({
        export_format: format,
        export_context: exportContext,
    })
}

interface DataTableExportProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    fileNameForExport?: string
    excludedColumns?: string[]
}

export function DataTableExport({
    query,
    fileNameForExport,
    excludedColumns = [],
}: DataTableExportProps): JSX.Element | null {
    const { dataTableRows, columnsInResponse, columnsInQuery, queryWithDefaults } = useValues(dataTableLogic)
    const { startExport, createStaticCohort } = useActions(exportsLogic)
    const [isColumnsModalOpen, setIsColumnsModalOpen] = useState(false)
    const responseColumns = columnsInResponse ?? columnsInQuery
    const exportColumns = responseColumns.filter((column) => !excludedColumns.includes(column))
    const exportQuery = excludedColumns.length ? { ...query, columns: exportColumns } : query
    // A source whose columns only exist in the response has no names to offer here, so the
    // picker would open with nothing to pick and no way to export.
    const pickableColumns = exportColumnsForQuery(exportQuery)
    const exportRows = excludedColumns.length
        ? projectExportRows(dataTableRows ?? [], responseColumns, exportColumns)
        : dataTableRows

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns = isEventsQuery(source) && source.select.includes('*')
    const showExportClipboardButtons =
        isPersonsNode(source) || isEventsQuery(source) || isHogQLQuery(source) || isMarketingAnalyticsTableQuery(source)
    const canSaveAsCohort = isActorsQuery(source)

    // Creating an export requires editor access to the export resource.
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )

    return (
        <>
            <LemonMenu
                items={[
                    {
                        label: 'Export current columns',
                        items: [
                            {
                                label: 'CSV',
                                onClick: () => {
                                    void startDownload(
                                        exportQuery,
                                        true,
                                        startExport,
                                        ExporterFormat.CSV,
                                        fileNameForExport
                                    )
                                },
                            },
                            {
                                label: 'XLSX',
                                onClick: () => {
                                    void startDownload(
                                        exportQuery,
                                        true,
                                        startExport,
                                        ExporterFormat.XLSX,
                                        fileNameForExport
                                    )
                                },
                            },
                        ],
                    },
                    canExportAllColumns && {
                        label: 'Export all columns',
                        items: [
                            {
                                label: 'CSV',
                                onClick: () =>
                                    void startDownload(
                                        exportQuery,
                                        false,
                                        startExport,
                                        ExporterFormat.CSV,
                                        fileNameForExport
                                    ),
                            },
                            {
                                label: 'XLSX',
                                onClick: () =>
                                    void startDownload(
                                        exportQuery,
                                        false,
                                        startExport,
                                        ExporterFormat.XLSX,
                                        fileNameForExport
                                    ),
                            },
                        ],
                    },
                    pickableColumns.length > 0 && {
                        label: 'Select columns…',
                        onClick: () => setIsColumnsModalOpen(true),
                        'data-attr': 'data-table-export-select-columns',
                    },
                    showExportClipboardButtons && {
                        label: 'Copy to clipboard',
                        items: [
                            {
                                label: 'CSV',
                                onClick: () => {
                                    if (exportRows) {
                                        copyTableToCsv(exportRows, exportColumns, queryWithDefaults)
                                    }
                                },
                                'data-attr': 'copy-csv-to-clipboard',
                            },
                            {
                                label: 'JSON',
                                onClick: () => {
                                    if (exportRows) {
                                        copyTableToJson(exportRows, exportColumns, queryWithDefaults)
                                    }
                                },
                                'data-attr': 'copy-json-to-clipboard',
                            },
                            {
                                label: 'Excel',
                                onClick: () => {
                                    if (exportRows) {
                                        copyTableToExcel(exportRows, exportColumns, queryWithDefaults)
                                    }
                                },
                                'data-attr': 'copy-excel-to-clipboard',
                            },
                        ],
                    },
                    canSaveAsCohort && {
                        label: 'Save to cohort',
                        items: [
                            {
                                label: 'Save as static cohort',
                                onClick: () => {
                                    LemonDialog.openForm({
                                        title: 'Save as static cohort',
                                        description: 'This will create a cohort with the current list of people.',
                                        initialValues: {
                                            name: '',
                                        },
                                        content: (
                                            <LemonField name="name">
                                                <LemonInput
                                                    type="text"
                                                    data-attr="insight-name"
                                                    placeholder="Name of the new cohort"
                                                    autoFocus
                                                />
                                            </LemonField>
                                        ),
                                        errors: {
                                            name: (name) => (!name ? 'You must enter a name' : undefined),
                                        },
                                        onSubmit: async ({ name }) => createStaticCohort(name, source),
                                    })
                                },
                            },
                            {
                                label: 'Add to existing cohort',
                                onClick: () => {
                                    LemonDialog.open({
                                        title: 'Add to existing cohort',
                                        description: 'This will add the current list of people to a static cohort.',
                                        content: (closeDialog) => (
                                            <SaveToCohortModalContent closeModal={closeDialog} query={source} />
                                        ),
                                        primaryButton: null,
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                },
                            },
                        ],
                    },
                ].filter(Boolean)}
            >
                <LemonButton
                    type="secondary"
                    icon={<IconDownload />}
                    data-attr="data-table-export-menu"
                    size="small"
                    disabledReason={accessControlDisabledReason ?? undefined}
                >
                    Export{filterCount > 0 ? ` (${pluralize(filterCount, 'filter')})` : ''}
                </LemonButton>
            </LemonMenu>
            {isColumnsModalOpen && (
                <ExportColumnsModal
                    isOpen
                    columns={pickableColumns.map((name) => ({
                        name,
                        label: extractDisplayLabel(name),
                    }))}
                    formats={TABULAR_EXPORT_FORMATS}
                    onClose={() => setIsColumnsModalOpen(false)}
                    onExport={(format, columns) =>
                        void startDownload(exportQuery, true, startExport, format, fileNameForExport, columns)
                    }
                />
            )}
        </>
    )
}

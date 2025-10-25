import { useActions, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { SaveToCohortModalContent } from 'lib/components/SaveToCohortModalContent/SaveToCohortModalContent'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { copyTableToCsv, copyTableToExcel, copyTableToJson } from '~/queries/nodes/DataTable/clipboardUtils'
import {
    shouldOptimizeForExport,
    transformColumnsForExport,
    transformQuerySourceForExport,
} from '~/queries/nodes/DataTable/exportTransformers'
import { defaultDataTableColumns, removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { DataNode, DataTableNode } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isGroupsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
} from '~/queries/utils'
import { ExporterFormat } from '~/types'

import { dataTableLogic } from './dataTableLogic'

// Sync with posthog/hogql/constants.py
export const MAX_SELECT_RETURNED_ROWS = 50000

const columnDisallowList = ['person.$delete', '*']

export async function startDownload(
    query: DataTableNode,
    onlySelectedColumns: boolean,
    exportCall: (exportData: TriggerExportProps) => void,
    format: ExporterFormat = ExporterFormat.CSV,
    fileNameForExport?: string
): Promise<void> {
    const shouldOptimize = shouldOptimizeForExport(query)

    let exportSource = query.source

    const team = teamLogic.findMounted()?.values?.currentTeam
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES

    // Remove person column from the source otherwise export fails when there's 1000+ records
    if (shouldOptimize && isEventsQuery(query.source)) {
        exportSource = transformQuerySourceForExport(query.source, personDisplayNameProperties)
    }

    const exportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source) }
        : { source: exportSource }

    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    if (onlySelectedColumns) {
        let columns = (
            (isEventsQuery(query.source) || isActorsQuery(query.source) || isGroupsQuery(query.source)
                ? query.source.select
                : null) ??
            query.columns ??
            defaultDataTableColumns(query.source.kind)
        )?.filter((c) => c !== 'person.$delete')

        // Apply export optimizations to columns
        if (shouldOptimize && isEventsQuery(query.source)) {
            columns = transformColumnsForExport(columns, personDisplayNameProperties)
        } else if (isPersonsNode(query.source)) {
            columns = columns.map((c: string) => (removeExpressionComment(c) === 'person' ? 'email' : c))
        }

        if (columns.includes('person')) {
            columns = columns.map((c: string) => (c === 'person' ? 'person.distinct_ids.0' : c))
        }

        columns = columns.filter((n: string) => !columnDisallowList.includes(n))
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
}

export function DataTableExport({ query, fileNameForExport }: DataTableExportProps): JSX.Element | null {
    const { dataTableRows, columnsInResponse, columnsInQuery, queryWithDefaults } = useValues(dataTableLogic)
    const { startExport, createStaticCohort } = useActions(exportsLogic)

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns =
        (isEventsQuery(source) && source.select.includes('*')) || isPersonsNode(source) || isActorsQuery(source)
    const showExportClipboardButtons =
        isPersonsNode(source) || isEventsQuery(source) || isHogQLQuery(source) || isMarketingAnalyticsTableQuery(source)
    const canSaveAsCohort = isActorsQuery(source)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Export current columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                void startDownload(query, true, startExport, ExporterFormat.CSV, fileNameForExport)
                            },
                        },
                        {
                            label: 'XLSX',
                            onClick: () => {
                                void startDownload(query, true, startExport, ExporterFormat.XLSX, fileNameForExport)
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
                                void startDownload(query, false, startExport, ExporterFormat.CSV, fileNameForExport),
                        },
                        {
                            label: 'XLSX',
                            onClick: () =>
                                void startDownload(query, false, startExport, ExporterFormat.XLSX, fileNameForExport),
                        },
                    ],
                },
                showExportClipboardButtons && {
                    label: 'Copy to clipboard',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                if (dataTableRows) {
                                    copyTableToCsv(
                                        dataTableRows,
                                        columnsInResponse ?? columnsInQuery,
                                        queryWithDefaults
                                    )
                                }
                            },
                            'data-attr': 'copy-csv-to-clipboard',
                        },
                        {
                            label: 'JSON',
                            onClick: () => {
                                if (dataTableRows) {
                                    copyTableToJson(
                                        dataTableRows,
                                        columnsInResponse ?? columnsInQuery,
                                        queryWithDefaults
                                    )
                                }
                            },
                            'data-attr': 'copy-json-to-clipboard',
                        },
                        {
                            label: 'Excel',
                            onClick: () => {
                                if (dataTableRows) {
                                    copyTableToExcel(
                                        dataTableRows,
                                        columnsInResponse ?? columnsInQuery,
                                        queryWithDefaults
                                    )
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
            <LemonButton type="secondary" icon={<IconDownload />} data-attr="data-table-export-menu">
                Export{filterCount > 0 ? ` (${filterCount} filter${filterCount === 1 ? '' : 's'})` : ''}
            </LemonButton>
        </LemonMenu>
    )
}

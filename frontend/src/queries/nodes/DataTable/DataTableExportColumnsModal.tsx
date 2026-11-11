import { useState } from 'react'

import { IconCopy, IconDownload } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { ExporterFormat } from '~/types'

interface DataTableExportColumnsModalProps {
    isOpen: boolean
    onClose: () => void
    columns: string[]
    canCopy: boolean
    canDownload: boolean
    downloadDisabledReason?: string
    onCopy: (columns: string[], includeHeader: boolean) => void
    onDownload: (columns: string[], format: ExporterFormat) => void
}

export function DataTableExportColumnsModal({
    isOpen,
    onClose,
    columns,
    canCopy,
    canDownload,
    downloadDisabledReason,
    onCopy,
    onDownload,
}: DataTableExportColumnsModalProps): JSX.Element {
    const [selectedColumns, setSelectedColumns] = useState<string[]>([])
    const [includeHeader, setIncludeHeader] = useState(false)
    const orderedSelection = columns.filter((column) => selectedColumns.includes(column))
    const noColumnsReason = orderedSelection.length === 0 ? 'Select at least one column' : undefined

    // Resets after the close animation, so the content doesn't change while it fades out.
    const resetSelection = (): void => {
        setSelectedColumns([])
        setIncludeHeader(false)
    }

    const toggleColumn = (column: string, checked: boolean): void =>
        setSelectedColumns((current) => (checked ? [...current, column] : current.filter((c) => c !== column)))

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            onAfterClose={resetSelection}
            title="Export selected columns"
            description={
                canDownload
                    ? 'Downloads include every matching row. Copying includes only the rows loaded in the table.'
                    : 'Copying includes only the rows loaded in the table.'
            }
            footer={
                <>
                    {canDownload && (
                        <>
                            <LemonButton
                                type="secondary"
                                icon={<IconDownload />}
                                disabledReason={noColumnsReason ?? downloadDisabledReason}
                                onClick={() => {
                                    onDownload(orderedSelection, ExporterFormat.CSV)
                                    onClose()
                                }}
                                data-attr="data-table-export-selected-columns-csv"
                            >
                                Download CSV
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                icon={<IconDownload />}
                                disabledReason={noColumnsReason ?? downloadDisabledReason}
                                onClick={() => {
                                    onDownload(orderedSelection, ExporterFormat.XLSX)
                                    onClose()
                                }}
                                data-attr="data-table-export-selected-columns-xlsx"
                            >
                                Download XLSX
                            </LemonButton>
                        </>
                    )}
                    {canCopy && (
                        <LemonButton
                            type="primary"
                            icon={<IconCopy />}
                            disabledReason={noColumnsReason}
                            onClick={() => {
                                onCopy(orderedSelection, includeHeader)
                                onClose()
                            }}
                            data-attr="data-table-export-selected-columns-copy"
                        >
                            Copy to clipboard
                        </LemonButton>
                    )}
                </>
            }
        >
            <div className="flex flex-col gap-1 max-h-80 overflow-y-auto">
                {columns.map((column) => (
                    <LemonCheckbox
                        key={column}
                        checked={selectedColumns.includes(column)}
                        onChange={(checked) => toggleColumn(column, checked)}
                        label={extractExpressionComment(column)}
                        data-attr="data-table-export-selected-columns-option"
                    />
                ))}
            </div>
            {canCopy && (
                <>
                    <LemonDivider />
                    <LemonCheckbox
                        checked={includeHeader}
                        onChange={setIncludeHeader}
                        label="Include column names when copying"
                    />
                </>
            )}
        </LemonModal>
    )
}

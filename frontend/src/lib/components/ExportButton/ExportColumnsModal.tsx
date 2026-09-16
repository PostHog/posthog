import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { ExporterFormat } from '~/types'

import { exportFormatExtension } from './exporter'

// Only these carry a column per field, so only these can be narrowed down.
export const TABULAR_EXPORT_FORMATS = [ExporterFormat.CSV, ExporterFormat.XLSX]

// A daily trend over a year has a column per day, which is too many to scan.
const SEARCHABLE_FROM = 10

export interface ExportColumn {
    /** Sent to the exporter, so it has to match the column name the export produces. */
    name: string
    /** Shown to the user in place of the name. */
    label?: string
}

export interface ExportColumnsModalProps {
    isOpen: boolean
    columns: ExportColumn[]
    formats: ExporterFormat[]
    onClose: () => void
    onExport: (format: ExporterFormat, columns: string[]) => void
}

export function ExportColumnsModal({
    isOpen,
    columns,
    formats,
    onClose,
    onExport,
}: ExportColumnsModalProps): JSX.Element {
    const [selected, setSelected] = useState<string[]>(() => columns.map((column) => column.name))
    const [search, setSearch] = useState('')
    const selectedSet = new Set(selected)
    const matches = search
        ? columns.filter((column) => (column.label ?? column.name).toLowerCase().includes(search.toLowerCase()))
        : columns

    const toggle = (name: string, checked: boolean): void => {
        // Rebuild from the source list so the file keeps the table's column order.
        setSelected(
            columns
                .filter((column) => (column.name === name ? checked : selectedSet.has(column.name)))
                .map((column) => column.name)
        )
    }

    const startExport = (format: ExporterFormat): void => {
        // pinned: analytics event and property names — renaming breaks dashboards
        posthog.capture('export columns selected', {
            export_format: format,
            selected_column_count: selected.length,
            available_column_count: columns.length,
            is_subset: selected.length < columns.length,
        })
        onExport(format, selected)
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Select columns to export"
            description="Columns you uncheck are left out of the file."
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    {formats.map((format) => (
                        <LemonButton
                            key={format}
                            type="primary"
                            data-attr={`export-columns-${exportFormatExtension(format)}`}
                            disabledReason={selected.length === 0 ? 'Select at least one column' : undefined}
                            onClick={() => startExport(format)}
                        >
                            {`Export .${exportFormatExtension(format)}`}
                        </LemonButton>
                    ))}
                </>
            }
        >
            <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                <span className="text-secondary">
                    {/* Each count gets its own element, so neither is a bare text node React tracks: once a
                        page-translation extension replaces such a node with a <font> element, React's writes
                        land on the detached node and the count freezes while the checkboxes keep updating
                        (react#11538). The numbers also opt out of translation. */}
                    <span translate="no">{selected.length}</span> of <span translate="no">{columns.length}</span>{' '}
                    selected
                </span>
                <div className="flex gap-2">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setSelected(columns.map((column) => column.name))}
                        disabledReason={selected.length === columns.length ? 'Every column is selected' : undefined}
                    >
                        Select all
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setSelected([])}
                        disabledReason={selected.length === 0 ? 'No column is selected' : undefined}
                    >
                        Clear all
                    </LemonButton>
                </div>
            </div>
            {columns.length > SEARCHABLE_FROM && (
                <LemonInput
                    type="search"
                    className="mb-2"
                    placeholder="Search columns"
                    value={search}
                    onChange={setSearch}
                />
            )}
            <div className="max-h-80 overflow-y-auto">
                {matches.length === 0 && <span className="text-secondary">No column matches your search.</span>}
                {matches.map((column) => (
                    <LemonCheckbox
                        key={column.name}
                        fullWidth
                        label={column.label ?? column.name}
                        checked={selectedSet.has(column.name)}
                        onChange={(checked) => toggle(column.name, checked)}
                    />
                ))}
            </div>
        </LemonModal>
    )
}

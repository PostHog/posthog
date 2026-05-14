import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonSelect, LemonTable, LemonTextArea } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { CatalogColumnDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import { catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

const SEMANTIC_TYPE_OPTIONS: { label: string; value: string }[] = [
    { label: 'Entity ID', value: 'entity_id' },
    { label: 'Foreign key', value: 'foreign_key' },
    { label: 'Timestamp', value: 'timestamp' },
    { label: 'Measure', value: 'measure' },
    { label: 'Dimension', value: 'dimension' },
    { label: 'Monetary', value: 'monetary' },
    { label: 'Free text', value: 'free_text' },
    { label: 'Enum', value: 'enum' },
    { label: 'UUID', value: 'uuid' },
    { label: 'Unknown', value: 'unknown' },
]

const PII_CLASS_OPTIONS: { label: string; value: string }[] = [
    { label: 'PII', value: 'pii' },
    { label: 'Sensitive', value: 'sensitive' },
    { label: 'Public', value: 'public' },
    { label: 'Unknown', value: 'unknown' },
]

interface Props {
    /** Hide the hogql type annotation for the narrow side panel. */
    compact?: boolean
}

export function CatalogDefinitionColumnsTable({ compact = false }: Props = {}): JSX.Element {
    const { definition, pendingColumnEdits } = useValues(catalogDefinitionSceneLogic)
    const { setColumnEdits } = useActions(catalogDefinitionSceneLogic)
    const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({})

    const columns = definition?.columns ?? []
    const toggleExpanded = (id: string): void => setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }))

    const tableColumns: LemonTableColumns<CatalogColumnDTOApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, column) => (
                <div className="py-1.5">
                    <span className="font-mono text-sm">{column.name}</span>
                    {!compact && column.hogql_type && (
                        <span className="ml-2 font-mono text-xs text-secondary">{column.hogql_type}</span>
                    )}
                </div>
            ),
        },
    ]

    if (columns.length === 0) {
        return (
            <div className="text-secondary text-sm border rounded p-4 text-center">
                No columns have been catalogued yet. They'll appear here once the agent traverses this table.
            </div>
        )
    }

    return (
        <LemonTable
            dataSource={columns}
            columns={tableColumns}
            rowKey={(c) => c.id}
            showHeader={false}
            onRow={(column) => ({
                // Don't toggle when the click bubbles up from the built-in expand
                // chevron — its own handler already fires onRowExpand/Collapse.
                onClick: (e) => {
                    if ((e.target as HTMLElement).closest('button')) {
                        return
                    }
                    toggleExpanded(column.id)
                },
                className: 'cursor-pointer',
            })}
            expandable={{
                isRowExpanded: (column) => !!expandedIds[column.id],
                onRowExpand: (column) => setExpandedIds((prev) => ({ ...prev, [column.id]: true })),
                onRowCollapse: (column) => setExpandedIds((prev) => ({ ...prev, [column.id]: false })),
                expandedRowRender: (column) => {
                    const edits = pendingColumnEdits[column.id]
                    const semanticTypeValue =
                        edits && 'semantic_type' in edits
                            ? (edits.semantic_type ?? null)
                            : (column.semantic_type ?? null)
                    const piiValue =
                        edits && 'pii_class' in edits ? (edits.pii_class ?? null) : (column.pii_class ?? null)
                    const descriptionValue =
                        edits && 'synthetic_description' in edits
                            ? (edits.synthetic_description ?? '')
                            : (column.description ?? '')
                    return (
                        <div className="p-3 bg-bg-light flex flex-col gap-3">
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <div className="text-xs font-medium mb-1">Type</div>
                                    <LemonSelect
                                        size="small"
                                        value={semanticTypeValue}
                                        options={SEMANTIC_TYPE_OPTIONS}
                                        onChange={(next) => setColumnEdits(column.id, { semantic_type: next ?? null })}
                                        placeholder="—"
                                        fullWidth
                                    />
                                </div>
                                <div>
                                    <div className="text-xs font-medium mb-1">PII class</div>
                                    <LemonSelect
                                        size="small"
                                        value={piiValue}
                                        options={PII_CLASS_OPTIONS}
                                        onChange={(next) => setColumnEdits(column.id, { pii_class: next ?? null })}
                                        placeholder="—"
                                        fullWidth
                                    />
                                </div>
                            </div>
                            <div>
                                <div className="text-xs font-medium mb-1">Description</div>
                                <LemonTextArea
                                    value={descriptionValue}
                                    placeholder="What this column represents — meaning, units, valid values, gotchas"
                                    onChange={(next) => setColumnEdits(column.id, { synthetic_description: next })}
                                    minRows={3}
                                />
                            </div>
                        </div>
                    )
                },
            }}
        />
    )
}

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { LemonSelect, LemonTable, LemonTextArea } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type {
    CatalogColumnDTOApi,
    PatchedUpdateColumnInputApi,
    PiiClassEnumApi,
    SemanticTypeEnumApi,
} from 'products/catalog/frontend/generated/api.schemas'

import { catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

const SEMANTIC_TYPE_OPTIONS: { label: string; value: SemanticTypeEnumApi }[] = [
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

const PII_CLASS_OPTIONS: { label: string; value: PiiClassEnumApi }[] = [
    { label: 'PII', value: 'pii' },
    { label: 'Sensitive', value: 'sensitive' },
    { label: 'Public', value: 'public' },
    { label: 'Unknown', value: 'unknown' },
]

const EXPAND_ANIMATION_MS = 200

interface Props {
    /** Hide the hogql type annotation for the narrow side panel. */
    compact?: boolean
}

export function CatalogDefinitionColumnsTable({ compact = false }: Props = {}): JSX.Element {
    const { definition, pendingColumnEdits } = useValues(catalogDefinitionSceneLogic)
    const { setColumnEdits } = useActions(catalogDefinitionSceneLogic)
    const [expanded, setExpanded] = useState<Record<string, { wanted: boolean; rendered: boolean }>>({})

    const columns = definition?.columns ?? []
    const toggleExpanded = (id: string): void => {
        setExpanded((prev) => {
            const current = prev[id] ?? { wanted: false, rendered: false }
            if (current.wanted) {
                // Closing: drop wanted now, keep rendered until the height transition finishes.
                window.setTimeout(() => {
                    setExpanded((p) => ({ ...p, [id]: { wanted: false, rendered: false } }))
                }, EXPAND_ANIMATION_MS)
                return { ...prev, [id]: { wanted: false, rendered: true } }
            }
            return { ...prev, [id]: { wanted: true, rendered: true } }
        })
    }

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
                // LemonTable.TableRow auto-applies hover:bg-accent-highlight-secondary
                // when a row has onClick; override with ! so it doesn't read as a
                // destructive action.
                className: 'cursor-pointer hover:!bg-surface-secondary transition-colors',
            })}
            expandable={{
                isRowExpanded: (column) => !!expanded[column.id]?.rendered,
                onRowExpand: (column) => toggleExpanded(column.id),
                onRowCollapse: (column) => toggleExpanded(column.id),
                expandedRowRender: (column) => (
                    <AnimatedColumnDetails
                        column={column}
                        open={!!expanded[column.id]?.wanted}
                        pendingEdits={pendingColumnEdits[column.id]}
                        onChange={(edits) => setColumnEdits(column.id, edits)}
                    />
                ),
            }}
        />
    )
}

function AnimatedColumnDetails({
    column,
    open,
    pendingEdits,
    onChange,
}: {
    column: CatalogColumnDTOApi
    open: boolean
    pendingEdits: PatchedUpdateColumnInputApi | undefined
    onChange: (edits: PatchedUpdateColumnInputApi) => void
}): JSX.Element | null {
    const { ref, height } = useResizeObserver({ box: 'border-box' })
    // Start hidden so an initial mount with open=true still triggers the
    // height transition from 0 → measured-height on the next frame.
    const [shown, setShown] = useState(false)
    useEffect(() => {
        const raf = window.requestAnimationFrame(() => setShown(open))
        return () => window.cancelAnimationFrame(raf)
    }, [open])

    const semanticTypeValue =
        pendingEdits && 'semantic_type' in pendingEdits
            ? (pendingEdits.semantic_type ?? null)
            : (column.semantic_type ?? null)
    const piiValue =
        pendingEdits && 'pii_class' in pendingEdits ? (pendingEdits.pii_class ?? null) : (column.pii_class ?? null)
    const descriptionValue =
        pendingEdits && 'synthetic_description' in pendingEdits
            ? (pendingEdits.synthetic_description ?? '')
            : (column.description ?? '')

    return (
        <div
            className="overflow-hidden transition-[height] duration-200 ease-in-out"
            style={{ height: shown ? height : 0 }}
        >
            <div ref={ref}>
                <div className="p-3 bg-bg-light flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <div className="text-xs font-medium mb-1">Type</div>
                            <LemonSelect
                                size="small"
                                value={semanticTypeValue}
                                options={SEMANTIC_TYPE_OPTIONS}
                                onChange={(next) => onChange({ semantic_type: next ?? null })}
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
                                onChange={(next) => onChange({ pii_class: next ?? null })}
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
                            onChange={(next) => onChange({ synthetic_description: next })}
                            minRows={3}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}

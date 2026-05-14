import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTable } from '@posthog/lemon-ui'

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
    /** Hide the hogql type column and tighten the layout for the narrow side panel. */
    compact?: boolean
}

export function CatalogDefinitionColumnsTable({ compact = false }: Props = {}): JSX.Element {
    const { definition, pendingColumnEdits } = useValues(catalogDefinitionSceneLogic)
    const { setColumnEdits, clearColumnEdits, saveColumn } = useActions(catalogDefinitionSceneLogic)

    const columns = definition?.columns ?? []

    const tableColumns: LemonTableColumns<CatalogColumnDTOApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, column) => <span className="font-mono text-sm">{column.name}</span>,
        },
        ...(compact
            ? []
            : [
                  {
                      title: 'Type',
                      key: 'type',
                      render: (_: unknown, column: CatalogColumnDTOApi) => (
                          <span className="font-mono text-xs text-secondary">{column.hogql_type ?? '—'}</span>
                      ),
                  },
              ]),
        {
            title: 'Semantic type',
            key: 'semantic_type',
            render: (_, column) => {
                const edits = pendingColumnEdits[column.id]
                const value =
                    edits && 'semantic_type' in edits ? (edits.semantic_type ?? null) : (column.semantic_type ?? null)
                return (
                    <LemonSelect
                        size="small"
                        value={value}
                        options={SEMANTIC_TYPE_OPTIONS}
                        onChange={(next) => setColumnEdits(column.id, { semantic_type: next ?? null })}
                        placeholder="—"
                    />
                )
            },
        },
        {
            title: 'PII',
            key: 'pii_class',
            render: (_, column) => {
                const edits = pendingColumnEdits[column.id]
                const value = edits && 'pii_class' in edits ? (edits.pii_class ?? null) : (column.pii_class ?? null)
                return (
                    <LemonSelect
                        size="small"
                        value={value}
                        options={PII_CLASS_OPTIONS}
                        onChange={(next) => setColumnEdits(column.id, { pii_class: next ?? null })}
                        placeholder="—"
                    />
                )
            },
        },
        {
            title: 'Description',
            key: 'description',
            render: (_, column) => {
                const edits = pendingColumnEdits[column.id]
                const value =
                    edits && 'synthetic_description' in edits
                        ? (edits.synthetic_description ?? '')
                        : (column.description ?? '')
                return (
                    <LemonInput
                        size="small"
                        value={value}
                        placeholder="Describe this column"
                        onChange={(next) => setColumnEdits(column.id, { synthetic_description: next })}
                    />
                )
            },
        },
        {
            title: '',
            key: 'actions',
            width: 64,
            render: (_, column) => {
                const dirty = !!pendingColumnEdits[column.id] && Object.keys(pendingColumnEdits[column.id]).length > 0
                if (!dirty) {
                    return null
                }
                return (
                    <div className="flex gap-1">
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            icon={<IconCheck />}
                            onClick={() => saveColumn(column.id)}
                            tooltip="Save column"
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => clearColumnEdits(column.id)}
                            tooltip="Discard changes"
                        />
                    </div>
                )
            },
        },
    ]

    if (columns.length === 0) {
        return (
            <div className="text-secondary text-sm border rounded p-4 text-center">
                No columns have been catalogued yet. They'll appear here once the agent traverses this table.
            </div>
        )
    }

    return <LemonTable dataSource={columns} columns={tableColumns} rowKey={(c) => c.id} />
}

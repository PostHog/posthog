import { LemonCollapse } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

export type DataWarehouseColumnsHintProps = {
    schemaColumns: DatabaseSchemaField[]
    tableName?: string
    // Destinations resolve a person and event from the synced row, so `{person}`/`{event}` are valid
    // globals there. Workflow triggers are row-scoped (no person/event), so they leave this false.
    personAvailable?: boolean
}

/**
 * Shows the columns of the selected warehouse table and how to reference them in templates.
 * Warehouse rows are delivered under `event.properties`, but `{record.<column>}` is the friendlier
 * alias users write (rewritten on save) — so we surface that form with click-to-copy.
 */
export function DataWarehouseColumnsHint({
    schemaColumns,
    tableName,
    personAvailable = false,
}: DataWarehouseColumnsHintProps): JSX.Element | null {
    if (!schemaColumns.length) {
        return null
    }

    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'columns',
                    header: tableName ? `Reference columns from ${tableName}` : 'Reference table columns',
                    content: (
                        <div className="flex flex-col gap-2">
                            <p className="mb-0 text-xs text-secondary">
                                Use <code>{'{record.<column>}'}</code> in your templates to insert a value from the
                                synced row.{' '}
                                {personAvailable ? (
                                    <>
                                        <code>{'{person}'}</code> and <code>{'{event}'}</code> are also available.{' '}
                                    </>
                                ) : null}
                                Click a column to copy its reference.
                            </p>
                            <div className="flex flex-wrap gap-1">
                                {schemaColumns.map((column) => (
                                    <LemonButton
                                        key={column.name}
                                        size="xsmall"
                                        type="secondary"
                                        tooltip={`Copy {record.${column.name}}`}
                                        onClick={() =>
                                            void copyToClipboard(`{record.${column.name}}`, 'column reference')
                                        }
                                    >
                                        {column.name}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}

import clsx from 'clsx'

import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { NotebookNodeSQLV2WarehouseTable } from '../NotebookNodeSQLV2'

export type NotebookWarehouseTableToggleProps = {
    saveToWarehouse: boolean
    warehouseTableName: string
    /** Prefills the table name the first time the user turns saving on. */
    defaultTableName: string
    onChange: (attrs: { saveToWarehouse: boolean; warehouseTableName: string }) => void
    /** How the last run's save went, from the run result. */
    lastSave?: NotebookNodeSQLV2WarehouseTable | null
    compact?: boolean
}

/** The "Save as warehouse table" control in a Python cell's output footer. */
export function NotebookWarehouseTableToggle({
    saveToWarehouse,
    warehouseTableName,
    defaultTableName,
    onChange,
    lastSave,
    compact,
}: NotebookWarehouseTableToggleProps): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-1.5">
            <LemonCheckbox
                checked={saveToWarehouse}
                onChange={(checked) =>
                    onChange({
                        saveToWarehouse: checked,
                        warehouseTableName: warehouseTableName || defaultTableName,
                    })
                }
                label="Save as warehouse table"
                size="xsmall"
                data-attr="notebook-save-warehouse-table"
            />
            {saveToWarehouse ? (
                <input
                    type="text"
                    className={clsx(
                        'px-1 font-mono bg-transparent rounded border border-primary focus:outline-none focus:ring-1 focus:ring-primary text-secondary',
                        compact ? 'w-44 text-xxs' : 'w-56 text-xs'
                    )}
                    value={warehouseTableName}
                    onChange={(event) => onChange({ saveToWarehouse, warehouseTableName: event.target.value })}
                    placeholder="Table name"
                    aria-label="Warehouse table name"
                    spellCheck={false}
                />
            ) : null}
            {saveToWarehouse && lastSave ? (
                lastSave.error ? (
                    <span className="text-danger">{lastSave.error}</span>
                ) : (
                    <Link to={urls.sqlEditor({ query: `SELECT * FROM ${lastSave.name}` })} target="_blank">
                        Saved to {lastSave.name}
                    </Link>
                )
            ) : null}
        </span>
    )
}

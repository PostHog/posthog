import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { LocalFrameSummary } from '../Nodes/notebookNodeContent'
import { NotebookNodeType } from '../types'
import { notebookLogic } from './notebookLogic'
import { CatalogTablePreview, notebookSchemaBrowserLogic } from './notebookSchemaBrowserLogic'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const PREVIEW_MAX_ROWS = 10
const PREVIEW_MAX_COLUMNS = 6

const formatPreviewCell = (value: unknown): string => {
    if (value === null || value === undefined) {
        return ''
    }
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    try {
        return JSON.stringify(value)
    } catch {
        return String(value)
    }
}

const PreviewTable = ({ columns, rows }: { columns: string[]; rows: any[][] }): JSX.Element => {
    const shownColumns = columns.slice(0, PREVIEW_MAX_COLUMNS)
    const shownRows = rows.slice(0, PREVIEW_MAX_ROWS)
    const tableColumns: LemonTableColumn<Record<string, any>, keyof Record<string, any> | undefined>[] =
        shownColumns.map((column, index) => ({
            title: column,
            key: `${column}-${index}`,
            dataIndex: column,
            render: (value) => <span className="font-mono text-xs whitespace-nowrap">{formatPreviewCell(value)}</span>,
        }))
    const dataSource = shownRows.map((row, rowIndex) => ({
        __rowId: rowIndex,
        ...Object.fromEntries(shownColumns.map((column, columnIndex) => [column, row[columnIndex] ?? null])),
    }))

    return (
        <div className="space-y-1">
            <div className="overflow-x-auto">
                <LemonTable
                    data-attr="notebook-schema-browser-preview"
                    columns={tableColumns}
                    dataSource={dataSource}
                    embedded
                    size="small"
                    rowKey="__rowId"
                    emptyState="No rows to display."
                />
            </div>
            {columns.length > shownColumns.length ? (
                <div className="text-xs text-muted">
                    Showing {shownColumns.length} of {columns.length} columns.
                </div>
            ) : null}
        </div>
    )
}

const ColumnList = ({ columns }: { columns: { name: string; type: string }[] }): JSX.Element => (
    <div className="space-y-0.5">
        {columns.map((column) => (
            <div key={column.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="font-mono truncate">{column.name}</span>
                <span className="text-muted shrink-0">{column.type}</span>
            </div>
        ))}
    </div>
)

const FrameDetail = ({ frame }: { frame: LocalFrameSummary }): JSX.Element => {
    if (!frame.result) {
        return (
            <div className="space-y-2">
                <div className="text-xs text-muted">Not run yet — definition only.</div>
                {frame.code ? (
                    <pre className="bg-bg-light border border-border rounded p-2 text-xs font-mono whitespace-pre-wrap max-h-60 overflow-y-auto">
                        {frame.code}
                    </pre>
                ) : null}
            </div>
        )
    }

    const dtypesByColumn = Object.fromEntries(frame.result.types)
    const columns = frame.result.columns.map((column) => ({
        name: column,
        type: dtypesByColumn[column] ?? '',
    }))

    return (
        <div className="space-y-2">
            <div className="text-xs text-muted">
                {frame.result.rowCount} rows × {frame.result.columns.length} columns
            </div>
            <ColumnList columns={columns} />
            {frame.result.firstPage.length > 0 ? (
                <PreviewTable columns={frame.result.columns} rows={frame.result.firstPage} />
            ) : null}
        </div>
    )
}

const TableDetail = ({
    table,
    preview,
    previewLoading,
    onPreview,
}: {
    table: DatabaseSchemaTable
    preview: CatalogTablePreview | null
    previewLoading: boolean
    onPreview: () => void
}): JSX.Element => {
    const columns = Object.values(table.fields).map((field) => ({ name: field.name, type: field.type }))
    const previewMatchesTable = preview?.tableName === table.name

    return (
        <div className="space-y-2">
            <ColumnList columns={columns} />
            <LemonButton size="xsmall" type="secondary" onClick={onPreview} loading={previewLoading}>
                Preview
            </LemonButton>
            {previewMatchesTable ? <PreviewTable columns={preview.columns} rows={preview.rows} /> : null}
        </div>
    )
}

const ItemRow = ({
    label,
    meta,
    selected,
    onClick,
    children,
}: {
    label: string
    meta?: JSX.Element | string | null
    selected: boolean
    onClick: () => void
    children?: JSX.Element | null
}): JSX.Element => (
    <div>
        <LemonButton size="xsmall" fullWidth active={selected} onClick={onClick} sideIcon={<span>{meta}</span>}>
            <span className="font-mono text-xs truncate">{label}</span>
        </LemonButton>
        {selected && children ? <div className="pl-2 py-2 border-l border-border ml-2">{children}</div> : null}
    </div>
)

const SectionHeader = ({ title, count }: { title: string; count: number }): JSX.Element => (
    <div className="flex items-center justify-between text-xs font-semibold text-muted uppercase tracking-wide pt-2">
        <span>{title}</span>
        <span>{count}</span>
    </div>
)

export const NotebookSchemaBrowser = (): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const { setShowSchemaBrowser } = useActions(notebookSettingsLogic)
    const logic = notebookSchemaBrowserLogic({ shortId })
    useAttachedLogic(logic, notebookLogic)
    const {
        searchTerm,
        selection,
        filteredFrames,
        filteredPosthogTables,
        filteredWarehouseTables,
        filteredViews,
        databaseLoading,
        tablePreview,
        tablePreviewLoading,
    } = useValues(logic)
    const { setSearchTerm, setSelection, previewCatalogTable, loadDatabase } = useActions(logic)

    const toggleFrame = (nodeId: string): void => {
        setSelection(selection?.type === 'frame' && selection.nodeId === nodeId ? null : { type: 'frame', nodeId })
    }
    const toggleTable = (tableName: string): void => {
        setSelection(
            selection?.type === 'table' && selection.tableName === tableName ? null : { type: 'table', tableName }
        )
    }

    const renderTableSection = (title: string, tables: DatabaseSchemaTable[]): JSX.Element => (
        <>
            <SectionHeader title={title} count={tables.length} />
            {tables.map((table) => (
                <ItemRow
                    key={table.id}
                    label={table.name}
                    meta={
                        table.row_count != null ? <span className="text-xs text-muted">{table.row_count}</span> : null
                    }
                    selected={selection?.type === 'table' && selection.tableName === table.name}
                    onClick={() => toggleTable(table.name)}
                >
                    <TableDetail
                        table={table}
                        preview={tablePreview}
                        previewLoading={tablePreviewLoading}
                        onPreview={() => previewCatalogTable(table.name)}
                    />
                </ItemRow>
            ))}
            {tables.length === 0 ? <div className="text-xs text-muted px-2">None</div> : null}
        </>
    )

    return (
        <LemonWidget
            className="NotebookColumn__widget"
            title="Schema"
            onClose={() => setShowSchemaBrowser(false)}
            actions={
                <LemonButton size="xsmall" type="secondary" onClick={() => loadDatabase()} loading={databaseLoading}>
                    Refresh
                </LemonButton>
            }
        >
            <div className="space-y-1 p-2" data-attr="notebook-schema-browser">
                <LemonInput
                    type="search"
                    size="small"
                    fullWidth
                    placeholder="Search tables and dataframes"
                    value={searchTerm}
                    onChange={setSearchTerm}
                />

                <SectionHeader title="Local dataframes" count={filteredFrames.length} />
                {filteredFrames.map((frame) => (
                    <ItemRow
                        key={frame.nodeId}
                        label={frame.name}
                        meta={
                            <span className="flex items-center gap-1">
                                {frame.result ? (
                                    <span className="text-xs text-muted whitespace-nowrap">
                                        {frame.result.rowCount}×{frame.result.columns.length}
                                    </span>
                                ) : null}
                                <LemonTag size="small" type={frame.result ? 'success' : 'default'}>
                                    {frame.nodeType === NotebookNodeType.Python ? 'Python' : 'SQL'}
                                </LemonTag>
                            </span>
                        }
                        selected={selection?.type === 'frame' && selection.nodeId === frame.nodeId}
                        onClick={() => toggleFrame(frame.nodeId)}
                    >
                        <FrameDetail frame={frame} />
                    </ItemRow>
                ))}
                {filteredFrames.length === 0 ? (
                    <div className="text-xs text-muted px-2">No SQL or Python cells yet.</div>
                ) : null}

                {databaseLoading && filteredPosthogTables.length === 0 ? (
                    <div className="flex items-center gap-2 text-muted text-xs pt-2">
                        <Spinner textColored />
                        Loading schema
                    </div>
                ) : (
                    <>
                        {renderTableSection('PostHog tables', filteredPosthogTables)}
                        {renderTableSection('Warehouse tables', filteredWarehouseTables)}
                        {renderTableSection('Views', filteredViews)}
                    </>
                )}
            </div>
        </LemonWidget>
    )
}

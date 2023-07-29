import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useValues } from 'kea'
import { databaseSceneLogic, DatabaseSceneRow } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { DatabaseTable } from './DatabaseTable'

export function DatabaseTablesContainer(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseSceneLogic)
    return (
        <DatabaseTables
            tables={filteredTables}
            loading={databaseLoading}
            renderRow={(row: DatabaseSceneRow) => {
                return (
                    <div className="px-4 py-3">
                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={row.name} tables={filteredTables} />
                        </div>
                    </div>
                )
            }}
        />
    )
}

interface DatabaseTablesProps<T extends Record<string, any>> {
    tables: T[]
    loading: boolean
    renderRow: (row: T) => JSX.Element
    extraColumns?: LemonTableColumns<T>
}

export function DatabaseTables<T extends DatabaseSceneRow>({
    tables,
    loading,
    renderRow,
    extraColumns = [],
}: DatabaseTablesProps<T>): JSX.Element {
    return (
        <>
            <LemonTable
                loading={loading}
                dataSource={tables}
                columns={[
                    {
                        title: 'Table',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderTable(table, obj: T) {
                            const query: DataTableNode = {
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.HogQLQuery,
                                    // TODO: Use `hogql` tag?
                                    query: `SELECT ${obj.columns
                                        .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                        .map(({ key }) => key)} FROM ${table} LIMIT 100`,
                                },
                            }
                            return (
                                <div className="flex">
                                    <Link to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
                                        <code>{table}</code>
                                    </Link>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        dataIndex: 'name',
                        render: function RenderType() {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    PostHog
                                </LemonTag>
                            )
                        },
                    },
                    ...extraColumns,
                ]}
                expandable={{
                    expandedRowRender: renderRow,
                    rowExpandable: () => true,
                    noIndent: true,
                }}
            />
        </>
    )
}

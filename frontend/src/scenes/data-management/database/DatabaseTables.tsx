import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useValues } from 'kea'
import { databaseSceneLogic, DatabaseSceneRow } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { DatabaseTable } from './DatabaseTable'

export function DatabaseTables(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseSceneLogic)

    return (
        <>
            <LemonTable
                loading={databaseLoading}
                dataSource={filteredTables}
                columns={[
                    {
                        title: 'Table',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderTable(table, obj: DatabaseSceneRow) {
                            const query: DataTableNode = {
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.HogQLQuery,
                                    query: `SELECT ${obj.columns
                                        .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                        .map(({ key }) => key)
                                        .join(', ')} FROM ${table} LIMIT 100`,
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
                ]}
                expandable={{
                    expandedRowRender: function renderExpand(row) {
                        return (
                            <div className="px-4 py-3">
                                <DatabaseTable table={row.name} />
                            </div>
                        )
                    },
                    rowExpandable: () => true,
                    noIndent: true,
                }}
            />
        </>
    )
}

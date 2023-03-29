import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { useActions, useValues } from 'kea'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { urls } from 'scenes/urls'
import { DataTableNode, NodeKind } from '~/queries/schema'

export function DatabaseTables(): JSX.Element {
    const { filteredTables, loading } = useValues(databaseSceneLogic)
    const { editDataBeachTable } = useActions(databaseSceneLogic)

    return (
        <>
            <LemonTable
                loading={loading}
                dataSource={filteredTables}
                columns={[
                    {
                        title: 'Table',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderTable(table) {
                            const query: DataTableNode = {
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.HogQLQuery,
                                    query: `SELECT * FROM ${table} LIMIT 10`,
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
                        key: 'engine',
                        dataIndex: 'engine',
                        render: function RenderType(engine) {
                            if (engine) {
                                return (
                                    <LemonTag type="warning" className="uppercase">
                                        {engine}
                                    </LemonTag>
                                )
                            } else {
                                return (
                                    <LemonTag type="default" className="uppercase">
                                        PostHog
                                    </LemonTag>
                                )
                            }
                        },
                    },
                    {
                        title: '',
                        width: 0,
                        key: 'dataBeachTableId',
                        dataIndex: 'dataBeachTableId',
                        render: function RenderActions(_, { dataBeachTableId }) {
                            if (dataBeachTableId) {
                                return (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton
                                                    status="stealth"
                                                    onClick={() => editDataBeachTable(dataBeachTableId)}
                                                    fullWidth
                                                >
                                                    Edit
                                                </LemonButton>
                                                <LemonDivider />
                                                <LemonButton status="danger" onClick={() => {}} fullWidth>
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                )
                            }
                        },
                    },
                ]}
                expandable={{
                    expandedRowRender: function renderExpand(row) {
                        return (
                            <div className="ml-12">
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

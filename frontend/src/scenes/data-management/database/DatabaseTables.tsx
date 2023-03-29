import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { useValues } from 'kea'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export function DatabaseTables(): JSX.Element {
    const { filteredTables, loading } = useValues(databaseSceneLogic)

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
                            return <code>{table}</code>
                        },
                    },
                    {
                        title: 'Type',
                        key: 'engine',
                        dataIndex: 'engine',
                        render: function RenderType(engine) {
                            if (engine) {
                                return (
                                    <LemonTag type="success" className="uppercase">
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
                ]}
                expandable={{
                    expandedRowRender: function renderExpand(row) {
                        return <DatabaseTable table={row.name} />
                    },
                    rowExpandable: () => true,
                    noIndent: true,
                }}
            />
        </>
    )
}

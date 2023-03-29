import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { useValues } from 'kea'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'

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
                                    <LemonTag type="warning" className="uppercase">
                                        🏝️️ {engine}
                                    </LemonTag>
                                )
                            } else {
                                return (
                                    <LemonTag type="default" className="uppercase">
                                        🦔 PostHog
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
                        render: function RenderActions(id) {
                            if (id) {
                                return (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton status="stealth" to={'#'} fullWidth>
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

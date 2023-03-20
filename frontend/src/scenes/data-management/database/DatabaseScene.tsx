import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from './databaseSceneLogic'
import { useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

export function DatabaseScene(): JSX.Element {
    const { database } = useValues(databaseSceneLogic)
    const tables = database ? Object.keys(database) : []

    return (
        <div data-attr="database-scene">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.Database} />

            <div className="mb-4">
                These are the database tables you can query in PostHog through{' '}
                <a href="https://posthog.com/manual/hogql" target="_blank">
                    HogQL
                </a>
                .
            </div>

            {tables.length === 0 ? <LemonTable loading={true} dataSource={[]} columns={[]} /> : null}

            {tables.map((table) => (
                <div key={table} className="mt-8">
                    <h2 className="subtitle">Table: {table}</h2>

                    <LemonTable
                        dataSource={database[table]}
                        columns={[
                            {
                                title: 'Column',
                                key: 'key',
                                dataIndex: 'key',
                                render: function RenderColumn(column) {
                                    return <code>{column}</code>
                                },
                            },
                            {
                                title: 'Type',
                                key: 'type',
                                dataIndex: 'type',
                                render: function RenderType(type) {
                                    if (type === 'virtual_table') {
                                        return <LemonTag type="default">Virtual Table</LemonTag>
                                    } else if (type === 'lazy_table') {
                                        return <LemonTag type="default">Reference</LemonTag>
                                    } else if (type === 'field_traverser') {
                                        return <LemonTag type="default">Expression</LemonTag>
                                    }
                                    return <LemonTag type="success">{type}</LemonTag>
                                },
                            },
                            {
                                title: 'Info',
                                key: 'info',
                                dataIndex: 'type',
                                render: function RenderInfo(type, field) {
                                    if (type === 'virtual_table') {
                                        return (
                                            <>
                                                Fields: <code>{(field as any).fields.join(', ')}</code>
                                            </>
                                        )
                                    } else if (type === 'lazy_table') {
                                        return (
                                            <>
                                                To table: <code>{String((field as any).table)}</code>
                                            </>
                                        )
                                    } else if (type === 'field_traverser' && Array.isArray((field as any).chain)) {
                                        return <code>{(field as any).chain.join('.')}</code>
                                    } else if (table == 'events' && type == 'json' && field.key == 'properties') {
                                        return (
                                            <Link to={urls.propertyDefinitions('event')}>Manage event properties</Link>
                                        )
                                    } else if (table == 'persons' && type == 'json' && field.key == 'properties') {
                                        return (
                                            <Link to={urls.propertyDefinitions('person')}>
                                                Manage person properties
                                            </Link>
                                        )
                                    }
                                    return ''
                                },
                            },
                        ]}
                    />
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: DatabaseScene,
    logic: databaseSceneLogic,
}

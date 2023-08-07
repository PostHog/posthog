import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { DatabaseSceneRow } from 'scenes/data-warehouse/types'
import { urls } from 'scenes/urls'

interface DatabaseTableProps {
    table: string
    tables: DatabaseSceneRow[]
}

export function DatabaseTable({ table, tables }: DatabaseTableProps): JSX.Element {
    return (
        <LemonTable
            size="small"
            dataSource={tables.find(({ name }) => name === table)?.columns ?? []}
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
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Virtual Table
                                </LemonTag>
                            )
                        } else if (type === 'lazy_table') {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Reference
                                </LemonTag>
                            )
                        } else if (type === 'field_traverser') {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Expression
                                </LemonTag>
                            )
                        }
                        return (
                            <LemonTag type="success" className="uppercase">
                                {type}
                            </LemonTag>
                        )
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
                            return <Link to={urls.propertyDefinitions('event')}>Manage event properties</Link>
                        } else if (table == 'persons' && type == 'json' && field.key == 'properties') {
                            return <Link to={urls.propertyDefinitions('person')}>Manage person properties</Link>
                        }
                        return ''
                    },
                },
            ]}
        />
    )
}

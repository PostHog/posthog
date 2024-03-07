import { LemonSwitch, LemonTable } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'

import { sourceModalLogic } from '../sourceModalLogic'
import { sourceFormLogic } from './sourceFormLogic'

export default function PostgresSchemaForm(): JSX.Element {
    useMountedLogic(sourceFormLogic({ sourceType: 'Postgres' }))
    const { selectSchema } = useActions(sourceModalLogic)
    const { databaseSchema } = useValues(sourceModalLogic)

    return (
        <div className="flex flex-col gap-2">
            <div>
                <LemonTable
                    emptyState="No schemas found"
                    dataSource={databaseSchema}
                    columns={[
                        {
                            title: 'Table',
                            key: 'table',
                            render: function RenderTable(_, schema) {
                                return schema.table
                            },
                        },
                        {
                            title: 'Sync',
                            key: 'should_sync',
                            render: function RenderShouldSync(_, schema) {
                                return (
                                    <LemonSwitch
                                        checked={schema.should_sync}
                                        onChange={() => {
                                            selectSchema(schema)
                                        }}
                                    />
                                )
                            },
                        },
                    ]}
                />
            </div>
        </div>
    )
}

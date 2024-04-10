import { LemonSwitch, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'

export default function PostgresSchemaForm(): JSX.Element {
    const { selectSchema } = useActions(sourceWizardLogic)
    const { databaseSchema } = useValues(sourceWizardLogic)

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

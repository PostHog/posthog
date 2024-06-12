import { LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'

export default function PostgresSchemaForm(): JSX.Element {
    const { toggleSchemaShouldSync } = useActions(sourceWizardLogic)
    const { databaseSchema } = useValues(sourceWizardLogic)
    const [toggleAllState, setToggleAllState] = useState(false)

    const toggleAllSwitches = (): void => {
        databaseSchema.forEach((schema) => {
            toggleSchemaShouldSync(schema, toggleAllState)
        })

        setToggleAllState(!toggleAllState)
    }

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
                            title: (
                                <>
                                    <span>Sync</span>
                                    <Link
                                        className="ml-2 w-[60px] overflow-visible"
                                        onClick={() => toggleAllSwitches()}
                                    >
                                        {toggleAllState ? 'Enable' : 'Disable'} all
                                    </Link>
                                </>
                            ),
                            key: 'should_sync',
                            render: function RenderShouldSync(_, schema) {
                                return (
                                    <LemonSwitch
                                        checked={schema.should_sync}
                                        onChange={(checked) => {
                                            toggleSchemaShouldSync(schema, checked)
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

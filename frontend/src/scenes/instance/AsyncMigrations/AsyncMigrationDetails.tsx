import React from 'react'
import { AsyncMigration, AsyncMigrationError, asyncMigrationsLogic } from './asyncMigrationsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { RedoOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

export function AsyncMigrationDetails({ asyncMigration }: { asyncMigration: AsyncMigration }): JSX.Element {
    const { asyncMigrationErrorsLoading, asyncMigrationErrors } = useValues(asyncMigrationsLogic)
    const { loadAsyncMigrationErrors } = useActions(asyncMigrationsLogic)

    const columns: LemonTableColumns<AsyncMigrationError> = [
        {
            title: 'id',
            dataIndex: 'id',
        },
        {
            title: 'Created At',
            render: function Render(_, asyncMigrationError: AsyncMigrationError): JSX.Element {
                const createdAt = asyncMigrationError.created_at
                return <div>{humanFriendlyDetailedTime(createdAt)}</div>
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
        },
    ]
    // Problem: the state is global and pressing the button below changes errors for all open pannels probably because
    // the value asyncMigrationErrors is global and gets changed
    // couldn't figure out how to load this on the opening of the details
    return (
        <div className="async-migrations-details-scene">
            <div className="mb float-right">
                <Button
                    icon={asyncMigrationErrorsLoading[asyncMigration.id] ? <Spinner size="sm" /> : <RedoOutlined />}
                    onClick={() =>
                        asyncMigration === undefined
                            ? console.log(`shouldnt be undefined ${asyncMigration}`)
                            : loadAsyncMigrationErrors(asyncMigration.id)
                    }
                >
                    Refresh errors
                </Button>
            </div>
            <LemonTable
                columns={columns}
                dataSource={asyncMigrationErrors[asyncMigration.id]}
                loading={asyncMigrationErrorsLoading[asyncMigration.id]}
            />
        </div>
    )
}

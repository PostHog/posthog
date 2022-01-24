import React from 'react'
import { AsyncMigration, AsyncMigrationError, asyncMigrationsLogic } from './asyncMigrationsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { RedoOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

export function AsyncMigrationDetails({ asyncMigration }: { asyncMigration: AsyncMigration }): JSX.Element {
    const { asyncMigrationIndividualErrorsLoading, asyncMigrationErrors } = useValues(asyncMigrationsLogic)
    const { loadAsyncMigrationErrors } = useActions(asyncMigrationsLogic)

    const columns: LemonTableColumns<AsyncMigrationError> = [
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
    return (
        <div className="async-migrations-details-scene">
            <div className="mb float-right">
                <Button
                    icon={
                        asyncMigrationIndividualErrorsLoading[asyncMigration.id] ? (
                            <Spinner size="sm" />
                        ) : (
                            <RedoOutlined />
                        )
                    }
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
                loading={asyncMigrationIndividualErrorsLoading[asyncMigration.id]}
            />
        </div>
    )
}

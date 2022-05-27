import React from 'react'
import { AsyncMigration, AsyncMigrationError, asyncMigrationsLogic } from './asyncMigrationsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { useActions, useValues } from 'kea'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { LemonButton } from 'lib/components/LemonButton'
import { IconRefresh } from 'lib/components/icons'

export function AsyncMigrationDetails({ asyncMigration }: { asyncMigration: AsyncMigration }): JSX.Element {
    const { asyncMigrationErrorsLoading, asyncMigrationErrors } = useValues(asyncMigrationsLogic)
    const { loadAsyncMigrationErrors } = useActions(asyncMigrationsLogic)

    const columns: LemonTableColumns<AsyncMigrationError> = [
        {
            title: 'Error',
            dataIndex: 'description',
        },
        {
            title: (
                <LemonButton
                    icon={asyncMigrationErrorsLoading[asyncMigration.id] ? <Spinner size="sm" /> : <IconRefresh />}
                    onClick={() => loadAsyncMigrationErrors(asyncMigration.id)}
                    type="secondary"
                    size="small"
                >
                    Refresh errors
                </LemonButton>
            ),
            render: function Render(_, asyncMigrationError: AsyncMigrationError): JSX.Element {
                return <div>{humanFriendlyDetailedTime(asyncMigrationError.created_at)}</div>
            },
        },
    ]
    return (
        <LemonTable
            columns={columns}
            dataSource={asyncMigrationErrors[asyncMigration.id]}
            loading={asyncMigrationErrorsLoading[asyncMigration.id]}
            embedded
        />
    )
}

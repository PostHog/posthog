import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { AsyncMigration, AsyncMigrationError, asyncMigrationsLogic } from './asyncMigrationsLogic'

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
                    icon={asyncMigrationErrorsLoading[asyncMigration.id] ? <Spinner /> : <IconRefresh />}
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

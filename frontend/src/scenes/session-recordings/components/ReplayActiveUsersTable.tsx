import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo } from '@posthog/icons'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { PersonType } from '~/types'

import { replayActiveUsersTableLogic } from './replayActiveUsersTableLogic'

export const ReplayActiveUsersTable = (): JSX.Element => {
    const { countedUsers, countedUsersLoading } = useValues(replayActiveUsersTableLogic({ scene: 'templates' }))

    return (
        <div className="flex flex-col border rounded bg-surface-primary w-full px-4 py-2">
            <LemonTable
                embedded={true}
                columns={[
                    {
                        title: (
                            <>
                                <Tooltip title="Click a row to see recordings.">
                                    <div className="flex flex-row gap-2 items-center cursor-pointer">
                                        <IconInfo className="text-xl" /> Last 7 days most active users
                                    </div>
                                </Tooltip>
                            </>
                        ),
                        dataIndex: 'person',
                        align: 'left',
                        render: (p) => <PersonDisplay person={p as PersonType} withIcon={true} noLink={true} />,
                    },
                    { align: 'left', dataIndex: 'count', width: '10%' },
                ]}
                dataSource={countedUsers || []}
                loading={countedUsersLoading}
                onRow={(record) => {
                    return {
                        className: 'cursor-pointer hover:bg-surface-secondary',
                        onClick: () => {
                            router.actions.push(
                                urls.personByUUID(record.person.id as string) + '#activeTab=sessionRecordings'
                            )
                        },
                    }
                }}
            />
        </div>
    )
}

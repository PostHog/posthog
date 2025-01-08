import { IconEllipsis, IconMinus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTable, LemonTableColumns, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ErrorTrackingTeam } from 'lib/components/Errors/types'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useEffect } from 'react'

import { UserBasicType } from '~/types'

import { errorTrackingTeamsLogic } from '../errorTrackingTeamsLogic'

export const Teams = (): JSX.Element => {
    const { teams, teamsLoading } = useValues(errorTrackingTeamsLogic)
    const { ensureAllTeamsLoaded, openTeamCreationForm } = useActions(errorTrackingTeamsLogic)

    useEffect(() => {
        ensureAllTeamsLoaded()
    }, [ensureAllTeamsLoaded])

    const columns: LemonTableColumns<ErrorTrackingTeam> = [
        {
            title: 'Team',
            dataIndex: 'name',
            key: 'name',
        },
        {
            key: 'actions',
            render: (_, item: ErrorTrackingTeam) => <Actions team={item} />,
        },
    ]

    return (
        <div className="space-y-2">
            <LemonTable
                size="small"
                dataSource={teams}
                loading={teamsLoading}
                columns={columns}
                expandable={{
                    noIndent: true,
                    rowExpandable: (record) => record.members.length > 0,
                    expandedRowRender: (record) => <MembersTable teamId={record.id} members={record.members} />,
                }}
            />
            <LemonButton onClick={openTeamCreationForm} size="small" type="primary">
                Create team
            </LemonButton>
        </div>
    )
}

const Actions = ({ team }: { team: ErrorTrackingTeam }): JSX.Element => {
    const { addTeamMember, deleteTeam } = useActions(errorTrackingTeamsLogic)

    return (
        <div className="flex flex-row justify-end space-x-2">
            <LemonMenu
                items={[
                    {
                        label: 'Delete',
                        status: 'danger',
                        onClick: () => deleteTeam(team.id),
                    },
                ]}
            >
                <LemonButton icon={<IconEllipsis />} size="xsmall" />
            </LemonMenu>
            <MemberSelect
                excludedMembers={team.members.map((m) => m.id)}
                onChange={(user) => {
                    if (user) {
                        addTeamMember({ teamId: team.id, user: user })
                    }
                }}
                value={null}
                allowNone={false}
                defaultLabel="Add member"
                type="primary"
                size="xsmall"
            />
        </div>
    )
}

const MembersTable = ({
    teamId,
    members,
}: {
    teamId: ErrorTrackingTeam['id']
    members: UserBasicType[]
}): JSX.Element => {
    const { removeTeamMember } = useActions(errorTrackingTeamsLogic)

    const columns: LemonTableColumns<UserBasicType> = [
        {
            title: 'Members',
            key: 'name',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture user={member} showName />
            },
        },
        {
            key: 'actions',
            render: (_, item: UserBasicType) => {
                return (
                    <div className="flex flex-row justify-end">
                        <LemonButton
                            onClick={() => removeTeamMember({ teamId, user: item })}
                            icon={<IconMinus />}
                            type="secondary"
                            status="danger"
                            size="xsmall"
                        >
                            Remove
                        </LemonButton>
                    </div>
                )
            },
        },
    ]

    return <LemonTable size="small" showHeader={false} dataSource={members} columns={columns} embedded />
}

import { IconEllipsis, IconMinus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTable, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ErrorTrackingTeam } from 'lib/components/Errors/types'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useEffect } from 'react'

import { UserBasicType } from '~/types'

import { errorTrackingTeamsLogic } from '../errorTrackingTeamsLogic'

export const Teams = (): JSX.Element => {
    const { teams, teamsLoading } = useValues(errorTrackingTeamsLogic)
    const { loadTeams } = useActions(errorTrackingTeamsLogic)

    useEffect(() => {
        loadTeams()
    }, [])

    return (
        <LemonTable
            dataSource={teams}
            loading={teamsLoading}
            columns={[
                {
                    title: 'Team',
                    dataIndex: 'name',
                    key: 'name',
                },
                {
                    key: 'actions',
                    render: (_, item: ErrorTrackingTeam) => {
                        return (
                            <div className="flex flex-row justify-end space-x-2">
                                <LemonMenu items={[{ label: 'Delete', status: 'danger', onClick: () => {} }]}>
                                    <LemonButton icon={<IconEllipsis />} size="xsmall" />
                                </LemonMenu>
                                <MemberSelect
                                    onChange={() => {}}
                                    excludedMembers={item.members.map((member) => member.id)}
                                    value={null}
                                    allowNone={false}
                                >
                                    {() => (
                                        <LemonButton onClick={() => {}} size="xsmall" type="primary" className="m-2">
                                            Add member
                                        </LemonButton>
                                    )}
                                </MemberSelect>
                            </div>
                        )
                    },
                },
            ]}
            expandable={{
                noIndent: true,
                rowExpandable: (record) => record.members.length > 0,
                expandedRowRender: (record) => {
                    return (
                        <>
                            <LemonTable
                                size="small"
                                showHeader={false}
                                dataSource={record.members}
                                columns={[
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
                                                <div className="flex justify-end">
                                                    <LemonButton
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
                                ]}
                                embedded
                            />
                        </>
                    )
                },
            }}
        />
    )
}

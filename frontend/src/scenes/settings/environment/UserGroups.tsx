import { IconEllipsis, IconMinus } from '@posthog/icons'
import {
    LemonButton,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useEffect } from 'react'

import { UserBasicType, UserGroup } from '~/types'

import { userGroupsLogic } from './userGroupsLogic'

export const UserGroups = (): JSX.Element => {
    const { userGroups, userGroupsLoading } = useValues(userGroupsLogic)
    const { ensureAllGroupsLoaded, openGroupCreationForm } = useActions(userGroupsLogic)

    useEffect(() => {
        ensureAllGroupsLoaded()
    }, [ensureAllGroupsLoaded])

    const columns: LemonTableColumns<UserGroup> = [
        {
            title: 'Group',
            dataIndex: 'name',
            key: 'name',
            width: 0,
            className: 'whitespace-nowrap font-semibold',
        },
        {
            title: 'Members',
            key: 'members',
            dataIndex: 'members',
            render: (_, { members }) => {
                return members && members.length ? (
                    <ProfileBubbles
                        people={members.map((user) => ({
                            email: user.email,
                            name: user.first_name,
                            title: `${user.first_name} <${user.email}>`,
                        }))}
                    />
                ) : (
                    'No members'
                )
            },
        },
        {
            key: 'actions',
            render: (_, item: UserGroup) => <Actions group={item} />,
        },
    ]

    return (
        <div className="deprecated-space-y-2">
            <LemonTable
                size="small"
                dataSource={userGroups}
                loading={userGroupsLoading}
                columns={columns}
                expandable={{
                    noIndent: true,
                    rowExpandable: (record) => record.members.length > 0,
                    expandedRowRender: (record) => <MembersTable groupId={record.id} members={record.members} />,
                }}
            />
            <LemonButton onClick={openGroupCreationForm} size="small" type="primary">
                Create group
            </LemonButton>
        </div>
    )
}

const Actions = ({ group }: { group: UserGroup }): JSX.Element => {
    const { addMember, deleteUserGroup } = useActions(userGroupsLogic)

    return (
        <div className="flex flex-row justify-end deprecated-space-x-2">
            <LemonMenu
                items={[
                    {
                        label: 'Delete',
                        status: 'danger',
                        onClick: () => deleteUserGroup(group.id),
                    },
                ]}
            >
                <LemonButton icon={<IconEllipsis />} size="xsmall" />
            </LemonMenu>
            <MemberSelect
                excludedMembers={group.members.map((m) => m.id)}
                onChange={(user) => {
                    if (user) {
                        addMember({ id: group.id, user: user })
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

const MembersTable = ({ groupId, members }: { groupId: UserGroup['id']; members: UserBasicType[] }): JSX.Element => {
    const { removeMember } = useActions(userGroupsLogic)

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
                            onClick={() => removeMember({ id: groupId, user: item })}
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

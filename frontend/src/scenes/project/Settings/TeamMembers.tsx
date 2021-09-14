import React from 'react'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { teamMembersLogic } from './teamMembersLogic'
import { DeleteOutlined, ExclamationCircleOutlined, LogoutOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { OrganizationMembershipLevel } from 'lib/constants'
import { OrganizationMemberType, TeamType, UserType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'

function ActionsComponent(member: OrganizationMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { removeMember } = useActions(teamMembersLogic)

    if (!user) {
        return null
    }

    const currentMembershipLevel = currentOrganization?.membership_level ?? -1

    function handleClick(): void {
        if (!user) {
            throw Error
        }
        Modal.confirm({
            title: `${member.user.uuid == user.uuid ? 'Leave' : `Remove ${member.user.first_name} from`} organization ${
                user.organization?.name
            }?`,
            icon: <ExclamationCircleOutlined />,
            okText: member.user.uuid == user.uuid ? 'Leave' : 'Remove',
            okType: 'danger',
            cancelText: 'Cancel',
            onOk() {
                removeMember(member)
            },
        })
    }

    const allowDeletion =
        // higher-ranked users cannot be removed, at the same time the currently logged-in user can leave any time
        ((currentMembershipLevel >= OrganizationMembershipLevel.Admin && member.level <= currentMembershipLevel) ||
            member.user.uuid === user.uuid) &&
        // unless that user is the organization's owner, in which case they can't leave
        member.level !== OrganizationMembershipLevel.Owner

    return (
        <div>
            {allowDeletion && (
                <a className="text-danger" onClick={handleClick} data-attr="delete-org-membership">
                    {member.user.uuid !== user.uuid ? (
                        <DeleteOutlined title="Remove from organization" />
                    ) : (
                        <LogoutOutlined title="Leave organization" />
                    )}
                </a>
            )}
        </div>
    )
}

export interface MembersProps {
    user: UserType
    team: TeamType
}

export function TeamMembers({ user }: MembersProps): JSX.Element {
    const { allMembers, allMembersLoading } = useValues(teamMembersLogic)

    const columns: ColumnsType<OrganizationMemberType> = [
        {
            dataIndex: 'user_email',
            key: 'user_email',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture name={member.user.first_name} email={member.user.email} />
            },
            width: 32,
        },
        {
            title: 'Name',
            dataIndex: 'user_first_name',
            key: 'user_first_name',
            render: (firstName: string, member: Record<string, any>) =>
                member.user_id == user.uuid ? `${firstName} (me)` : firstName,
            sorter: (a, b) =>
                (a as OrganizationMemberType).user.first_name.localeCompare(
                    (b as OrganizationMemberType).user.first_name
                ),
        },
        {
            title: 'Email',
            dataIndex: 'user_email',
            key: 'user_email',
            sorter: (a, b) =>
                (a as OrganizationMemberType).user.email.localeCompare((b as OrganizationMemberType).user.email),
        },
        {
            title: 'Level',
            dataIndex: 'level',
            key: 'level',
            render: function LevelRender() {
                return 'foo'
            },
            sorter: (a, b) => (a as OrganizationMemberType).level - (b as OrganizationMemberType).level,
            defaultSortOrder: 'descend',
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt: string) => humanFriendlyDetailedTime(joinedAt),
            sorter: (a, b) =>
                (a as OrganizationMemberType).joined_at.localeCompare((b as OrganizationMemberType).joined_at),
            defaultSortOrder: 'ascend',
        },
        {
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: function ActionsRender(_, member) {
                return ActionsComponent(member as OrganizationMemberType)
            },
        },
    ]

    return (
        <>
            <h2 className="subtitle">Members</h2>
            <Table
                dataSource={allMembers}
                columns={columns}
                rowKey="membership_id"
                pagination={false}
                style={{ marginTop: '1rem' }}
                loading={allMembersLoading}
                data-attr="team-members-table"
            />
        </>
    )
}

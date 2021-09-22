import React from 'react'
import { Table, Button, Dropdown, Menu, Tooltip, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { MINIMUM_IMPLICIT_ACCESS_LEVEL, teamMembersLogic } from './teamMembersLogic'
import {
    DownOutlined,
    CrownFilled,
    UpOutlined,
    CloseCircleOutlined,
    LogoutOutlined,
    ExclamationCircleOutlined,
} from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { OrganizationMembershipLevel, TeamMembershipLevel } from 'lib/constants'
import { TeamType, UserType, FusedTeamMemberType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { userLogic } from 'scenes/userLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { teamLogic } from '../../teamLogic'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    teamMembershipLevelIntegers,
} from '../../../lib/utils/permissioning'
import { AddMembersModalWithButton } from './AddMembersModal'
import { RestrictedArea, RestrictionScope } from '../../../lib/components/RestrictedArea'

function LevelComponent(member: FusedTeamMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { changeUserAccessLevel } = useActions(teamMembersLogic)

    const myMembershipLevel = currentTeam ? currentTeam.effective_membership_level : null

    if (!user) {
        return null
    }

    function generateHandleClick(listLevel: TeamMembershipLevel): (event: React.MouseEvent) => void {
        return function handleClick(event: React.MouseEvent) {
            event.preventDefault()
            changeUserAccessLevel(member.user, listLevel)
        }
    }

    const isImplicit = member.organization_level >= OrganizationMembershipLevel.Admin
    const levelName = membershipLevelToName.get(member.level) ?? `unknown (${member.level})`

    const levelButton = (
        <Button
            data-attr="change-membership-level"
            icon={member.level === OrganizationMembershipLevel.Owner ? <CrownFilled /> : undefined}
            // Org admins have implicit access anyway, so it doesn't make sense to edit them
            disabled={isImplicit}
        >
            {levelName}
        </Button>
    )

    const allowedLevels = teamMembershipLevelIntegers.filter(
        (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
    )
    const disallowedReason = isImplicit
        ? `This user is a member of the project implicitly due to being an organization ${levelName}.`
        : getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

    return disallowedReason ? (
        <Tooltip title={disallowedReason}>{levelButton}</Tooltip>
    ) : (
        <Dropdown
            overlay={
                <Menu>
                    {allowedLevels.map((listLevel) => (
                        <Menu.Item key={`${member.user.uuid}-level-${listLevel}`}>
                            <a href="#" onClick={generateHandleClick(listLevel)} data-test-level={listLevel}>
                                {listLevel > member.level ? (
                                    <>
                                        <UpOutlined style={{ marginRight: '0.5rem' }} />
                                        Upgrade to project {membershipLevelToName.get(listLevel)}
                                    </>
                                ) : (
                                    <>
                                        <DownOutlined style={{ marginRight: '0.5rem' }} />
                                        Downgrade to project {membershipLevelToName.get(listLevel)}
                                    </>
                                )}
                            </a>
                        </Menu.Item>
                    ))}
                </Menu>
            }
        >
            {levelButton}
        </Dropdown>
    )
}

function ActionsComponent(member: FusedTeamMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { removeMember } = useActions(teamMembersLogic)

    if (!user) {
        return null
    }

    function handleClick(): void {
        Modal.confirm({
            title: `${
                member.user.uuid == user?.uuid
                    ? 'Leave'
                    : `Remove ${member.user.first_name} (${member.user.email}) from`
            } project ${currentTeam?.name}?`,
            icon: <ExclamationCircleOutlined />,
            okText: member.user.uuid == user?.uuid ? 'Leave' : 'Remove',
            okType: 'danger',
            onOk() {
                removeMember({ member })
            },
        })
    }

    const allowDeletion =
        // You can leave, but only project admins can remove others
        ((currentTeam?.effective_membership_level &&
            currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin) ||
            member.user.uuid === user.uuid) &&
        // Only members without implicit access can leave or be removed
        member.organization_level < MINIMUM_IMPLICIT_ACCESS_LEVEL

    return allowDeletion ? (
        <a className="text-danger" onClick={handleClick} data-attr="delete-team-membership">
            {member.user.uuid !== user.uuid ? (
                <CloseCircleOutlined title="Remove from project" />
            ) : (
                <LogoutOutlined title="Leave project" />
            )}
        </a>
    ) : null
}

export interface MembersProps {
    user: UserType
    team: TeamType
}

export function TeamMembers({ user }: MembersProps): JSX.Element {
    const { allMembers, allMembersLoading } = useValues(teamMembersLogic)

    const columns: ColumnsType<FusedTeamMemberType> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture name={member.user.first_name} email={member.user.email} />
            },
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_first_name',
            render: (_, member) =>
                member.user.uuid == user.uuid ? `${member.user.first_name} (me)` : member.user.first_name,
            sorter: (a, b) => a.user.first_name.localeCompare(b.user.first_name),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, member) => member.user.email,
            sorter: (a, b) => a.user.email.localeCompare(b.user.email),
        },
        {
            title: 'Level',
            key: 'level',
            render: function LevelRender(_, member) {
                return LevelComponent(member)
            },
            sorter: (a, b) => a.level - b.level,
            defaultSortOrder: 'descend',
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt: string) => humanFriendlyDetailedTime(joinedAt),
            sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
            defaultSortOrder: 'ascend',
        },
        {
            key: 'actions',
            align: 'center',
            render: function ActionsRender(_, member) {
                return ActionsComponent(member)
            },
        },
    ]
    return (
        <>
            <h2 className="subtitle" id="members-with-project-access" style={{ justifyContent: 'space-between' }}>
                Members with Project Access
                <RestrictedArea
                    Component={AddMembersModalWithButton}
                    minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    scope={RestrictionScope.Project}
                />
            </h2>
            <Table
                dataSource={allMembers}
                columns={columns}
                rowKey="id"
                pagination={false}
                style={{ marginTop: '1rem' }}
                loading={allMembersLoading}
                data-attr="team-members-table"
            />
        </>
    )
}

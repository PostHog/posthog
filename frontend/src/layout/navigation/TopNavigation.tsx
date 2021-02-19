import React, { useState } from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconBuilding, IconMenu } from 'lib/components/icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { router } from 'kea-router'
import { Button, Dropdown } from 'antd'
import {
    ProjectOutlined,
    DownOutlined,
    ToolOutlined,
    PlusOutlined,
    UpOutlined,
    SearchOutlined,
    SettingOutlined,
    UserAddOutlined,
} from '@ant-design/icons'
import { guardPremiumFeature } from 'scenes/UpgradeModal'
import { sceneLogic } from 'scenes/sceneLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { hot } from 'react-hot-loader/root'
import { isMobile, platformCommandControlKey } from 'lib/utils'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { BulkInviteModal } from 'scenes/organization/TeamMembers/BulkInviteModal'
import { UserType } from '~/types'

export function WhoAmI({ user }: { user: UserType }): JSX.Element {
    return (
        <div className="whoami cursor-pointer" data-attr="top-navigation-whoami">
            <div className="pp">{user.name[0]?.toUpperCase()}</div>
            <div className="details hide-lte-lg">
                <span>{user.name}</span>
                <span>{user.organization?.name}</span>
            </div>
        </div>
    )
}

export const TopNavigation = hot(_TopNavigation)
export function _TopNavigation(): JSX.Element {
    const {
        setMenuCollapsed,
        setChangelogModalOpen,
        updateCurrentOrganization,
        updateCurrentProject,
        setInviteMembersModalOpen,
    } = useActions(navigationLogic)
    const { menuCollapsed, systemStatus, updateAvailable, changelogModalOpen, inviteMembersModalOpen } = useValues(
        navigationLogic
    )
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { showUpgradeModal } = useActions(sceneLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const { push } = router.actions
    const { showPalette } = useActions(commandPaletteLogic)
    const [projectModalShown, setProjectModalShown] = useState(false) // TODO: Move to Kea (using useState for backwards-compatibility with TopSelectors.tsx)
    const [organizationModalShown, setOrganizationModalShown] = useState(false) // TODO: Same as above

    const whoAmIDropdown = (
        <div className="navigation-top-dropdown whoami-dropdown">
            <div className="whoami" style={{ paddingRight: 16, paddingLeft: 16 }}>
                <div className="pp">{user?.name[0]?.toUpperCase()}</div>
                <div className="details">
                    <span>{user?.email}</span>
                    <span>{user?.organization?.name}</span>
                </div>
            </div>
            <div className="text-center mt" style={{ paddingRight: 16, paddingLeft: 16 }}>
                <div>
                    <Button
                        type="primary"
                        icon={<UserAddOutlined />}
                        onClick={() => setInviteMembersModalOpen(true)}
                        data-attr="top-menu-invite-team-members"
                    >
                        Invite Team Members
                    </Button>
                </div>
                <div style={{ marginTop: 12 }}>
                    <LinkButton
                        to="/organization/members"
                        data-attr="top-menu-item-org-settings"
                        style={{ width: '100%' }}
                        icon={<SettingOutlined />}
                    >
                        Organization Settings
                    </LinkButton>
                </div>
                {user?.is_multi_tenancy ? (
                    <div className="mt-05">
                        <Link to="/organization/billing" data-attr="top-menu-item-billing">
                            Billing
                        </Link>
                    </div>
                ) : (
                    <div className="mt-05">
                        <Link to="/instance/licenses" data-attr="top-menu-item-licenses">
                            Licenses
                        </Link>
                    </div>
                )}
                <div className="mt-05">
                    <Link to="/me/settings" data-attr="top-menu-item-me">
                        My account
                    </Link>
                </div>
            </div>
            <div className="divider mt-05" />
            <div className="organizations">
                {user?.organizations.map((organization) => {
                    if (organization.id == user.organization?.id) {
                        return undefined
                    }
                    return (
                        <a key={organization.id} onClick={() => updateCurrentOrganization(organization.id)}>
                            <IconBuilding /> {organization.name}
                        </a>
                    )
                })}
                <a
                    style={{ color: 'var(--muted)', display: 'flex', justifyContent: 'center' }}
                    onClick={() =>
                        guardPremiumFeature(
                            user,
                            showUpgradeModal,
                            'organizations_projects',
                            'multiple organizations',
                            () => {
                                setOrganizationModalShown(true)
                            },
                            {
                                cloud: false,
                                selfHosted: true,
                            }
                        )
                    }
                >
                    <PlusOutlined style={{ marginRight: 8, fontSize: 18 }} /> New organization
                </a>
            </div>
            <div className="divider mb-05" />
            <div className="text-center">
                <a onClick={logout} data-attr="top-menu-item-logout">
                    Log out
                </a>
            </div>
        </div>
    )

    const projectDropdown = (
        <div className="navigation-top-dropdown project-dropdown">
            <div className="dp-title">SELECT A PROJECT</div>
            <div className="projects">
                {user?.organization?.teams &&
                    user.organization.teams.map((team) => {
                        return (
                            <a onClick={() => updateCurrentProject(team.id, '/')} key={team.id}>
                                <span style={{ flexGrow: 1 }}>{team.name}</span>
                                <span
                                    className="settings"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        if (team.id === user?.team?.id) {
                                            push('/project/settings')
                                        } else {
                                            updateCurrentProject(team.id, '/project/settings')
                                        }
                                    }}
                                >
                                    <ToolOutlined />
                                </span>
                            </a>
                        )
                    })}
            </div>
            <div className="divider mt mb-05" />
            <div className="text-center">
                <a
                    onClick={() =>
                        guardPremiumFeature(
                            user,
                            showUpgradeModal,
                            'organizations_projects',
                            'multiple projects',
                            () => {
                                setProjectModalShown(true)
                            }
                        )
                    }
                >
                    <PlusOutlined /> Create new project
                </a>
            </div>
        </div>
    )

    return (
        <>
            <div className="navigation-spacer" />
            <div className={`navigation-top${sceneConfig.plain ? ' full-width' : ''}`}>
                <div style={{ justifyContent: 'flex-start' }}>
                    <div className="hide-gte-lg menu-toggle" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                        <IconMenu />
                    </div>
                    <div className="hide-lte-lg ml-05">
                        {!isMobile() && (
                            <Badge
                                data-attr="command-palette-toggle"
                                onClick={showPalette}
                                tooltip={`Toggle command palette (${platformCommandControlKey('K')})`}
                                icon={<SearchOutlined />}
                                className="mr"
                                type="primary"
                            />
                        )}
                        {(!user?.is_multi_tenancy || user.is_staff) && (
                            <Badge
                                data-attr="system-status-badge"
                                type={systemStatus ? 'success' : 'danger'}
                                onClick={() => push('/instance/status')}
                                tooltip={systemStatus ? 'All systems operational' : 'Potential system issue'}
                                className="mr"
                            />
                        )}
                        {!user?.is_multi_tenancy && (
                            <Badge
                                data-attr="update-indicator-badge"
                                type={updateAvailable ? 'warning' : undefined}
                                tooltip={updateAvailable ? 'New version available' : 'PostHog is up-to-date'}
                                icon={<UpOutlined />}
                                onClick={() => setChangelogModalOpen(true)}
                            />
                        )}
                    </div>
                </div>
                <div className="project-chooser">
                    <Dropdown overlay={projectDropdown} trigger={['click']} placement="bottomCenter">
                        <div style={{ height: '100%' }} className="cursor-pointer flexed">
                            <ProjectOutlined className="mr-05" />
                            {user?.team?.name} <DownOutlined className="ml-05" />
                        </div>
                    </Dropdown>
                </div>
                {user && (
                    <div>
                        <Dropdown overlay={whoAmIDropdown} trigger={['click']}>
                            <div>
                                <WhoAmI user={user} />
                            </div>
                        </Dropdown>
                    </div>
                )}
            </div>
            <BulkInviteModal visible={inviteMembersModalOpen} onClose={() => setInviteMembersModalOpen(false)} />
            <CreateProjectModal isVisible={projectModalShown} setIsVisible={setProjectModalShown} />
            <CreateOrganizationModal isVisible={organizationModalShown} setIsVisible={setOrganizationModalShown} />
            {changelogModalOpen && <ChangelogModal onDismiss={() => setChangelogModalOpen(false)} />}
        </>
    )
}

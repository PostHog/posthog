import React, { useState } from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconBuilding, IconMenu } from 'lib/components/icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { router } from 'kea-router'
import { Button, Card, Dropdown, Switch } from 'antd'
import {
    ProjectOutlined,
    DownOutlined,
    ToolOutlined,
    PlusOutlined,
    UpOutlined,
    SearchOutlined,
    SettingOutlined,
    UserAddOutlined,
    InfoCircleOutlined,
} from '@ant-design/icons'
import { guardPremiumFeature } from 'scenes/UpgradeModal'
import { sceneLogic, urls } from 'scenes/sceneLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { isMobile, platformCommandControlKey } from 'lib/utils'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { BulkInviteModal } from 'scenes/organization/Settings/BulkInviteModal'
import { UserType } from '~/types'
import { CreateInviteModalWithButton } from 'scenes/organization/Settings/CreateInviteModal'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Environments, FEATURE_FLAGS } from 'lib/constants'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Tooltip } from 'lib/components/Tooltip'

export function WhoAmI({ user }: { user: UserType }): JSX.Element {
    return (
        <div className="whoami cursor-pointer" data-attr="top-navigation-whoami">
            <ProfilePicture name={user.first_name} email={user.email} />
            <div className="details hide-lte-lg">
                <span>{user.first_name}</span>
                <span>{user.organization?.name}</span>
            </div>
        </div>
    )
}

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed, setChangelogModalOpen, setInviteMembersModalOpen, setFilteredEnvironment } = useActions(
        navigationLogic
    )
    const {
        menuCollapsed,
        systemStatus,
        updateAvailable,
        changelogModalOpen,
        inviteMembersModalOpen,
        filteredEnvironment,
    } = useValues(navigationLogic)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { billing } = useValues(billingLogic)
    const { logout, updateCurrentTeam, updateCurrentOrganization } = useActions(userLogic)
    const { showUpgradeModal } = useActions(sceneLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const { push } = router.actions
    const { showPalette } = useActions(commandPaletteLogic)
    const [projectModalShown, setProjectModalShown] = useState(false) // TODO: Move to Kea (using useState for backwards-compatibility with TopSelectors.tsx)
    const [organizationModalShown, setOrganizationModalShown] = useState(false) // TODO: Same as above
    const { featureFlags } = useValues(featureFlagLogic)

    const whoAmIDropdown = (
        <div className="navigation-top-dropdown whoami-dropdown">
            <div className="whoami" style={{ paddingRight: 16, paddingLeft: 16 }}>
                <ProfilePicture name={user?.first_name} email={user?.email} />
                <div className="details">
                    <span>{user?.email}</span>
                    <span>{user?.organization?.name}</span>
                </div>
            </div>
            <div className="text-center mt" style={{ paddingRight: 16, paddingLeft: 16 }}>
                {preflight?.cloud && billing?.should_display_current_bill && (
                    <Link to={urls.organizationBilling()} data-attr="top-menu-billing-usage">
                        <Card
                            bodyStyle={{ padding: 4, fontWeight: 'bold' }}
                            style={{ marginBottom: 16, cursor: 'pointer' }}
                        >
                            <span className="text-small text-muted">
                                <b>Current usage</b>
                            </span>
                            <div style={{ fontSize: '1.05rem' }}>
                                {billing?.current_bill_amount !== undefined && billing?.current_bill_amount !== null ? (
                                    `$${billing?.current_bill_amount?.toLocaleString()}`
                                ) : (
                                    <>
                                        Unavailable{' '}
                                        <Tooltip title="We can't show your current bill amount right now. Please check back in a few minutes. If you keep seeing this message, contact us.">
                                            <InfoCircleOutlined />
                                        </Tooltip>
                                    </>
                                )}
                            </div>
                        </Card>
                    </Link>
                )}
                <div>
                    {preflight?.email_service_available ? (
                        <Button
                            type="primary"
                            icon={<UserAddOutlined />}
                            onClick={() => setInviteMembersModalOpen(true)}
                            data-attr="top-menu-invite-team-members"
                            style={{ width: '100%' }}
                        >
                            Invite Team Members
                        </Button>
                    ) : (
                        <CreateInviteModalWithButton block />
                    )}
                </div>
                <div style={{ marginTop: 10 }}>
                    <LinkButton
                        to={urls.organizationSettings()}
                        data-attr="top-menu-item-org-settings"
                        style={{ width: '100%' }}
                        icon={<SettingOutlined />}
                    >
                        Organization Settings
                    </LinkButton>
                </div>
                {preflight?.cloud ? (
                    <div className="mt-05">
                        <Link to={urls.organizationBilling()} data-attr="top-menu-item-billing">
                            Billing
                        </Link>
                    </div>
                ) : (
                    <div className="mt-05">
                        <Link to={urls.instanceLicenses()} data-attr="top-menu-item-licenses">
                            Licenses
                        </Link>
                    </div>
                )}
                <div className="mt-05">
                    <Link to={urls.mySettings()} data-attr="top-menu-item-me">
                        My account
                    </Link>
                </div>
            </div>
            {((user?.organizations.length ?? 0) > 1 || preflight?.can_create_org) && <div className="divider mt-05" />}
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
                {preflight?.can_create_org && (
                    <a
                        style={{ color: 'var(--muted)', display: 'flex', justifyContent: 'center' }}
                        onClick={() =>
                            guardPremiumFeature(
                                user,
                                preflight,
                                showUpgradeModal,
                                'organizations_projects',
                                'multiple organizations',
                                'Organizations group people building products together. An organization can then have multiple projects.',
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
                )}
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
                            <a onClick={() => updateCurrentTeam(team.id, '/')} key={team.id}>
                                <span style={{ flexGrow: 1 }}>{team.name}</span>
                                <span
                                    className="settings"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        if (team.id === user?.team?.id) {
                                            push(urls.projectSettings())
                                        } else {
                                            updateCurrentTeam(team.id, '/project/settings')
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
                            preflight,
                            showUpgradeModal,
                            'organizations_projects',
                            'multiple projects',
                            'Projects allow you to separate data and configuration for different products or environments.',
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
                        {(!preflight?.cloud || user?.is_staff) && (
                            <Link to={urls.systemStatus()}>
                                <Badge
                                    data-attr="system-status-badge"
                                    type={systemStatus ? 'success' : 'danger'}
                                    tooltip={systemStatus ? 'All systems operational' : 'Potential system issue'}
                                    className="mr"
                                />
                            </Link>
                        )}
                        {!preflight?.cloud && (
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
                        {featureFlags[FEATURE_FLAGS.TEST_ENVIRONMENT] && (
                            <div className="global-environment-switch">
                                <label
                                    htmlFor="global-environment-switch"
                                    className={filteredEnvironment === Environments.TEST ? 'test' : ''}
                                >
                                    <Tooltip title="Toggle to view only test or production data everywhere. Click to learn more.">
                                        <a href="https://posthog.com/docs" target="_blank" rel="noopener">
                                            <InfoCircleOutlined />
                                        </a>
                                    </Tooltip>
                                    {filteredEnvironment === Environments.PRODUCTION ? 'Production' : 'Test'}
                                </label>
                                <Switch
                                    // @ts-expect-error - below works even if it's not defined as a prop
                                    id="global-environment-switch"
                                    checked={filteredEnvironment === Environments.PRODUCTION}
                                    defaultChecked={filteredEnvironment === Environments.PRODUCTION}
                                    onChange={(val) =>
                                        setFilteredEnvironment(val ? Environments.PRODUCTION : Environments.TEST)
                                    }
                                />
                            </div>
                        )}
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

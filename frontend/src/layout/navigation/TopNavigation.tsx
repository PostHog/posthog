import React from 'react'
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
    CreditCardOutlined,
    KeyOutlined,
    SmileOutlined,
    StopOutlined,
} from '@ant-design/icons'
import { sceneLogic, urls } from 'scenes/sceneLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { isMobile, platformCommandControlKey } from 'lib/utils'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { BulkInviteModal } from 'scenes/organization/Settings/BulkInviteModal'
import { AvailableFeature, TeamBasicType, UserType } from '~/types'
import { CreateInviteModalWithButton } from 'scenes/organization/Settings/CreateInviteModal'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Environments, FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Tooltip } from 'lib/components/Tooltip'
import { teamLogic } from '../../scenes/teamLogic'
import { organizationLogic } from '../../scenes/organizationLogic'

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

function ProjectRow({ team }: { team: TeamBasicType }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(userLogic)
    const { push } = useActions(router)

    const isCurrent = team.id === currentTeam?.id
    const isRestricted = !team.effective_membership_level

    return (
        <button
            key={team.id}
            className="plain-button"
            type="button"
            onClick={(e) => {
                if (!isCurrent && !isRestricted) {
                    updateCurrentTeam(team.id, '/')
                } else {
                    e.preventDefault() // Prevent dropdown from hiding if can't switch project
                }
            }}
            disabled={isCurrent || isRestricted}
            style={{
                cursor: isCurrent || isRestricted ? 'default' : undefined,
                color: isRestricted ? 'var(--text-muted)' : undefined,
            }}
        >
            {isRestricted ? <StopOutlined className="mr-05" /> : <ProjectOutlined className="mr-05" />}
            <span style={{ flexGrow: 1, fontWeight: isCurrent ? 'bold' : 'normal' }}>{team.name}</span>
            {!isRestricted && (
                <span
                    className="subaction"
                    onClick={(e) => {
                        e.stopPropagation()
                        if (isCurrent) {
                            push(urls.projectSettings())
                        } else {
                            updateCurrentTeam(team.id, '/project/settings')
                        }
                    }}
                >
                    <ToolOutlined />
                </span>
            )}
        </button>
    )
}

export function TopNavigation(): JSX.Element {
    const {
        setMenuCollapsed,
        setChangelogModalOpen,
        setInviteMembersModalOpen,
        setFilteredEnvironment,
        setProjectModalShown,
        setOrganizationModalShown,
    } = useActions(navigationLogic)
    const {
        menuCollapsed,
        systemStatus,
        updateAvailable,
        changelogModalOpen,
        inviteMembersModalOpen,
        filteredEnvironment,
        projectModalShown,
        organizationModalShown,
    } = useValues(navigationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { billing } = useValues(billingLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { logout, updateCurrentOrganization } = useActions(userLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const { showPalette } = useActions(commandPaletteLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isCurrentProjectRestricted = currentTeam && !currentTeam.effective_membership_level
    const isProjectCreationForbidden =
        !currentOrganization?.membership_level ||
        currentOrganization.membership_level < OrganizationMembershipLevel.Admin

    const whoAmIDropdown = (
        <div className="navigation-top-dropdown whoami-dropdown">
            <div className="whoami" style={{ margin: 16 }}>
                <ProfilePicture name={user?.first_name} email={user?.email} />
                <div className="details">
                    <span>{user?.email}</span>
                    <span>{user?.organization?.name}</span>
                </div>
            </div>
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
            {preflight?.email_service_available ? (
                <Button
                    type="primary"
                    icon={<UserAddOutlined />}
                    onClick={() => setInviteMembersModalOpen(true)}
                    data-attr="top-menu-invite-team-members"
                >
                    Invite team members
                </Button>
            ) : (
                <CreateInviteModalWithButton />
            )}
            <LinkButton to={urls.mySettings()} data-attr="top-menu-item-me" icon={<SmileOutlined />}>
                My account
            </LinkButton>
            {preflight?.cloud ? (
                <LinkButton
                    to={urls.organizationBilling()}
                    data-attr="top-menu-item-billing"
                    icon={<CreditCardOutlined />}
                >
                    Billing
                </LinkButton>
            ) : (
                <LinkButton to={urls.instanceLicenses()} data-attr="top-menu-item-licenses" icon={<KeyOutlined />}>
                    Licenses
                </LinkButton>
            )}
            <LinkButton
                to={urls.organizationSettings()}
                data-attr="top-menu-item-org-settings"
                icon={<SettingOutlined />}
            >
                Organization settings
            </LinkButton>
            {
                <div className="organizations">
                    {user?.organizations
                        .sort((orgA, orgB) =>
                            orgA.id === user?.organization?.id ? -2 : orgA.name.localeCompare(orgB.name)
                        )
                        .map(
                            (organization) =>
                                organization.id !== user.organization?.id && (
                                    <button
                                        type="button"
                                        className="plain-button"
                                        key={organization.id}
                                        onClick={() => updateCurrentOrganization(organization.id)}
                                    >
                                        <IconBuilding className="mr-05" style={{ width: 14 }} />
                                        {organization.name}
                                    </button>
                                )
                        )}
                    {preflight?.can_create_org && (
                        <button
                            type="button"
                            className="plain-button text-primary"
                            onClick={() =>
                                guardAvailableFeature(
                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
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
                            <PlusOutlined className="mr-05" />
                            Create new organization
                        </button>
                    )}
                </div>
            }
            <button type="button" onClick={logout} className="bottom-button" data-attr="top-menu-item-logout">
                Log out
            </button>
        </div>
    )

    const projectDropdown = (
        <div className="navigation-top-dropdown project-dropdown">
            <div className="title">Select project</div>
            <div className="projects">
                {currentOrganization?.teams &&
                    currentOrganization.teams
                        .sort((teamA, teamB) =>
                            teamA.id === currentTeam?.id
                                ? -2
                                : teamA.effective_membership_level
                                ? 2
                                : teamA.name.localeCompare(teamB.name)
                        )
                        .map((team) => <ProjectRow key={team.id} team={team} />)}
            </div>
            <button
                type="button"
                className="plain-button text-primary"
                disabled={isProjectCreationForbidden}
                onClick={() =>
                    guardAvailableFeature(
                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                        'multiple projects',
                        'Projects allow you to separate data and configuration for different products or environments.',
                        () => {
                            setProjectModalShown(true)
                        }
                    )
                }
                style={{
                    cursor: isProjectCreationForbidden ? 'not-allowed' : 'default',
                    color: isProjectCreationForbidden ? 'var(--text-muted)' : undefined,
                }}
            >
                <PlusOutlined className="mr-05" />
                Create new project
            </button>
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
                <div className="project-chooser-container">
                    <Dropdown
                        overlay={projectDropdown}
                        className="project-chooser"
                        overlayClassName="navigation-top-dropdown-overlay"
                        trigger={['click']}
                        placement="bottomCenter"
                    >
                        <div>
                            {isCurrentProjectRestricted ? (
                                <StopOutlined className="mr-05" />
                            ) : (
                                <ProjectOutlined className="mr-05" />
                            )}
                            {currentTeam ? currentTeam.name : <i>Choose project</i>}
                            <DownOutlined className="ml-05" />
                        </div>
                    </Dropdown>
                </div>
                {user && (
                    <>
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
                        <Dropdown
                            overlay={whoAmIDropdown}
                            overlayClassName="navigation-top-dropdown-overlay"
                            trigger={['click']}
                        >
                            <div>
                                <WhoAmI user={user} />
                            </div>
                        </Dropdown>
                    </>
                )}
            </div>
            <BulkInviteModal visible={inviteMembersModalOpen} onClose={() => setInviteMembersModalOpen(false)} />
            <CreateProjectModal isVisible={projectModalShown} setIsVisible={setProjectModalShown} />
            <CreateOrganizationModal isVisible={organizationModalShown} setIsVisible={setOrganizationModalShown} />
            {changelogModalOpen && <ChangelogModal onDismiss={() => setChangelogModalOpen(false)} />}
        </>
    )
}

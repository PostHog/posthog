import React from 'react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { LemonRow } from '../../../lib/components/LemonRow'
import {
    IconCheckmark,
    IconOffline,
    IconLogout,
    IconUpdate,
    IconExclamation,
    IconBill,
    IconArrowDropDown,
    IconSettings,
    IconCorporate,
    IconPlus,
} from 'lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from '../../../lib/components/Link'
import { urls } from '../../../scenes/urls'
import { navigationLogic } from '../navigationLogic'
import { LicenseType, OrganizationBasicType } from '../../../types'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/preflightLogic'
import { licenseLogic, isLicenseExpired } from '../../../scenes/instance/Licenses/licenseLogic'
import { identifierToHuman } from '../../../lib/utils'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import {
    AccessLevelIndicator,
    NewOrganizationButton,
    OtherOrganizationButton,
} from '~/layout/navigation/OrganizationSwitcher'
import { dayjs } from 'lib/dayjs'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonButtonPropsBase } from '@posthog/lemon-ui'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

function SitePopoverSection({ title, children }: { title?: string | JSX.Element; children: any }): JSX.Element {
    return (
        <div className="SitePopover__section">
            {title && <h5 className="flex items-center">{title}</h5>}
            {children}
        </div>
    )
}

function AccountInfo(): JSX.Element {
    const { user } = useValues(userLogic)
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <div className="AccountInfo">
            <ProfilePicture name={user?.first_name} email={user?.email} size="xl" />
            <div className="AccountInfo__identification SitePopover__main-info">
                <strong>{user?.first_name}</strong>
                <div className="supplement" title={user?.email}>
                    {user?.email}
                </div>
            </div>
            <Tooltip title="Account settings" placement="left">
                <LemonButton
                    to={urls.mySettings()}
                    onClick={closeSitePopover}
                    data-attr="top-menu-item-me"
                    type="stealth"
                    icon={<IconSettings style={{ fontSize: '1.4rem' }} />}
                />
            </Tooltip>
        </div>
    )
}

function CurrentOrganization({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <LemonRow icon={<Lettermark name={organization.name} />} fullWidth>
            <>
                <div className="SitePopover__main-info SitePopover__organization">
                    <strong>{organization.name}</strong>
                    <AccessLevelIndicator organization={organization} />
                </div>
                <Tooltip title="Organization settings" placement="left">
                    <LemonButton
                        to={urls.organizationSettings()}
                        onClick={closeSitePopover}
                        data-attr="top-menu-item-org-settings"
                        type="stealth"
                        icon={<IconSettings />}
                    />
                </Tooltip>
            </>
        </LemonRow>
    )
}

export function InviteMembersButton({
    center = false,
    type = 'default',
}: {
    center?: boolean
    type?: LemonButtonPropsBase['type']
}): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() => {
                closeSitePopover()
                showInviteModal()
                reportInviteMembersButtonClicked()
            }}
            center={center}
            type={type}
            fullWidth
            data-attr="top-menu-invite-team-members"
        >
            Invite members
        </LemonButton>
    )
}

function License({ license, expired }: { license: LicenseType | null; expired: boolean | null }): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <LemonRow icon={<Lettermark name={license ? license.plan : '–'} />} fullWidth>
            <>
                <div className="SitePopover__main-info">
                    <div>{license ? `${identifierToHuman(license.plan)} plan` : 'Free plan'}</div>
                    {license &&
                        (!expired ? (
                            <div className="supplement">
                                Valid until {dayjs(license.valid_until).format('D MMM YYYY')}
                            </div>
                        ) : (
                            <div className="supplement supplement--danger">Expired!</div>
                        ))}
                </div>
                <Link
                    to={urls.instanceLicenses()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="top-menu-item-licenses"
                >
                    Manage license
                </Link>
            </>
        </LemonRow>
    )
}

function SystemStatus(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { systemStatus } = useValues(navigationLogic)

    return (
        <LemonRow
            status={systemStatus ? 'success' : 'danger'}
            icon={systemStatus ? <IconCheckmark /> : <IconOffline />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    {systemStatus ? 'All systems operational' : 'Potential system issue'}
                </div>
                <Link
                    to={urls.instanceStatus()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="system-status-badge"
                >
                    Instance status
                </Link>
            </>
        </LemonRow>
    )
}

function Version(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { updateAvailable, latestVersion } = useValues(navigationLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <LemonRow
            status={updateAvailable ? 'warning' : 'success'}
            icon={updateAvailable ? <IconUpdate /> : <IconCheckmark />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    <div>
                        Version <strong>{preflight?.posthog_version}</strong>
                    </div>
                    {updateAvailable && <div className="supplement">{latestVersion} is available</div>}
                </div>
                {latestVersion && (
                    <Link
                        href={`https://posthog.com/blog/the-posthog-array-${latestVersion.replace(/\./g, '-')}`}
                        target="_blank"
                        rel="noopener"
                        onClick={() => {
                            closeSitePopover()
                        }}
                        className="SitePopover__side-link"
                        data-attr="update-indicator-badge"
                    >
                        Release notes
                    </Link>
                )}
            </>
        </LemonRow>
    )
}

function AsyncMigrations(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { asyncMigrationsOk } = useValues(navigationLogic)

    return (
        <LemonRow
            status={asyncMigrationsOk ? 'success' : 'warning'}
            icon={asyncMigrationsOk ? <IconCheckmark /> : <IconUpdate />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    {asyncMigrationsOk ? 'Async migrations up-to-date' : 'Pending async migrations'}
                </div>
                <Link
                    to={urls.asyncMigrations()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="async-migrations-status-badge"
                >
                    Manage
                </Link>
            </>
        </LemonRow>
    )
}

function InstanceSettings(): JSX.Element | null {
    const { closeSitePopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return null
    }

    return (
        <Link to={urls.instanceSettings()}>
            <LemonButton
                icon={<IconCorporate style={{ color: 'var(--primary)' }} />}
                onClick={closeSitePopover}
                fullWidth
            >
                Instance settings
            </LemonButton>
        </Link>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconLogout />} type="stealth" fullWidth data-attr="top-menu-item-logout">
            Sign out
        </LemonButton>
    )
}

export function SitePopover(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { isSitePopoverOpen, systemStatus } = useValues(navigationLogic)
    const { toggleSitePopover, closeSitePopover } = useActions(navigationLogic)
    const { relevantLicense } = useValues(licenseLogic)
    useMountedLogic(licenseLogic)

    const expired = relevantLicense && isLicenseExpired(relevantLicense)

    return (
        <Popup
            visible={isSitePopoverOpen}
            className="SitePopover"
            onClickOutside={closeSitePopover}
            overlay={
                <>
                    <SitePopoverSection title="Signed in as">
                        <AccountInfo />
                    </SitePopoverSection>
                    <SitePopoverSection title="Current organization">
                        {currentOrganization && <CurrentOrganization organization={currentOrganization} />}
                        {preflight?.cloud && (
                            <LemonButton
                                onClick={closeSitePopover}
                                to={urls.organizationBilling()}
                                icon={<IconBill />}
                                fullWidth
                                data-attr="top-menu-item-billing"
                            >
                                Billing
                            </LemonButton>
                        )}
                        <InviteMembersButton />
                    </SitePopoverSection>
                    {(otherOrganizations.length > 0 || preflight?.can_create_org) && (
                        <SitePopoverSection title="Other organizations">
                            {otherOrganizations.map((otherOrganization) => (
                                <OtherOrganizationButton key={otherOrganization.id} organization={otherOrganization} />
                            ))}
                            {preflight?.can_create_org && <NewOrganizationButton />}
                        </SitePopoverSection>
                    )}
                    {(!(preflight?.cloud || preflight?.demo) || user?.is_staff) && (
                        <SitePopoverSection title="PostHog instance">
                            {!preflight?.cloud && <License license={relevantLicense} expired={expired} />}
                            <SystemStatus />
                            {!preflight?.cloud && <Version />}
                            <AsyncMigrations />
                            <InstanceSettings />
                        </SitePopoverSection>
                    )}
                    <SitePopoverSection>
                        <SignOutButton />
                    </SitePopoverSection>
                </>
            }
        >
            <div
                data-tooltip="profile-button"
                className="SitePopover__crumb"
                onClick={toggleSitePopover}
                data-attr="top-menu-toggle"
            >
                <div
                    className="SitePopover__profile-picture"
                    title={!systemStatus ? 'Potential system issue' : expired ? 'License expired' : undefined}
                >
                    <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                    {(!systemStatus || expired) && <IconExclamation className="SitePopover__danger" />}
                </div>
                <IconArrowDropDown />
            </div>
        </Popup>
    )
}

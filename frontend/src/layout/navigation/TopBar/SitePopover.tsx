import React from 'react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { LemonRow } from '../../../lib/components/LemonRow'
import {
    IconCheckmark,
    IconOffline,
    IconPlus,
    IconLogout,
    IconUpdate,
    IconExclamation,
    IconBill,
    IconArrowDropDown,
} from 'lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from '../../../lib/components/Link'
import { urls } from '../../../scenes/urls'
import { navigationLogic } from '../navigationLogic'
import { LicenseType, OrganizationBasicType } from '../../../types'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/logic'
import { licenseLogic } from '../../../scenes/instance/Licenses/logic'
import { identifierToHuman } from '../../../lib/utils'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import {
    AccessLevelIndicator,
    NewOrganizationButton,
    OtherOrganizationButton,
} from '~/layout/navigation/OrganizationSwitcher'
import { dayjs } from 'lib/dayjs'

function SitePopoverSection({ title, children }: { title?: string; children: any }): JSX.Element {
    return (
        <div className="SitePopover__section">
            {title && <h5>{title}</h5>}
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
            <Link
                to={urls.mySettings()}
                onClick={closeSitePopover}
                className="SitePopover__side-link"
                data-attr="top-menu-item-me"
            >
                Manage account
            </Link>
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
                <Link
                    to={urls.organizationSettings()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="top-menu-item-org-settings"
                >
                    Settings
                </Link>
            </>
        </LemonRow>
    )
}

function InviteMembersButton(): JSX.Element {
    const { closeSitePopover, showInviteModal } = useActions(navigationLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() => {
                closeSitePopover()
                showInviteModal()
            }}
            fullWidth
            data-attr="top-menu-invite-team-members"
        >
            Invite members
        </LemonButton>
    )
}

function License(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { licenses } = useValues(licenseLogic)

    const relevantLicense = licenses[0] as LicenseType | undefined

    return (
        <LemonRow icon={<Lettermark name={relevantLicense ? relevantLicense.plan : '–'} />} fullWidth>
            <>
                <div className="SitePopover__main-info">
                    <div>{relevantLicense ? `${identifierToHuman(relevantLicense.plan)} plan` : 'Free plan'}</div>
                    {relevantLicense && (
                        <div className="supplement">
                            Valid till {dayjs(relevantLicense.valid_until).format('D MMM YYYY')}
                        </div>
                    )}
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
                    to={urls.systemStatus()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="system-status-badge"
                >
                    System status
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
    useMountedLogic(licenseLogic)

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
                    {(!preflight?.cloud || user?.is_staff) && (
                        <SitePopoverSection title="PostHog status">
                            {!preflight?.cloud && <License />}
                            <SystemStatus />
                            {!preflight?.cloud && <Version />}
                        </SitePopoverSection>
                    )}
                    <SitePopoverSection>
                        <SignOutButton />
                    </SitePopoverSection>
                </>
            }
        >
            <div className="SitePopover__crumb" onClick={toggleSitePopover} data-attr="top-menu-toggle">
                <div
                    className="SitePopover__profile-picture"
                    title={systemStatus ? undefined : 'Potential system issue'}
                >
                    <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                    {!systemStatus && <IconExclamation className="SitePopover__danger" />}
                </div>
                <IconArrowDropDown />
            </div>
        </Popup>
    )
}

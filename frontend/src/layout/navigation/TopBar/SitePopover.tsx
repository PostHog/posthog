import { useActions, useMountedLogic, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
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
} from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from '../../../scenes/urls'
import { navigationLogic } from '../navigationLogic'
import { LicenseType, OrganizationBasicType } from '../../../types'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/preflightLogic'
import { licenseLogic, isLicenseExpired } from '../../../scenes/instance/Licenses/licenseLogic'
import { identifierToHuman } from 'lib/utils'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import {
    AccessLevelIndicator,
    NewOrganizationButton,
    OtherOrganizationButton,
} from '~/layout/navigation/OrganizationSwitcher'
import { dayjs } from 'lib/dayjs'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonButtonPropsBase } from '@posthog/lemon-ui'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

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
                    status="stealth"
                    icon={<IconSettings className="text-2xl" />}
                />
            </Tooltip>
        </div>
    )
}

function CurrentOrganization({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <Tooltip title="Organization settings" placement="left">
            <LemonButton
                data-attr="top-menu-item-org-settings"
                icon={<Lettermark name={organization.name} />}
                sideIcon={<IconSettings />}
                status="stealth"
                fullWidth
                to={urls.organizationSettings()}
                onClick={closeSitePopover}
            >
                <div className="SitePopover__main-info SitePopover__organization">
                    <strong>{organization.name}</strong>
                    <AccessLevelIndicator organization={organization} />
                </div>
            </LemonButton>
        </Tooltip>
    )
}

export function InviteMembersButton({
    center = false,
    type = 'tertiary',
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
    const { minorUpdateAvailable, anyUpdateAvailable, latestVersion } = useValues(navigationLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <LemonRow
            status={minorUpdateAvailable ? 'warning' : 'success'}
            icon={minorUpdateAvailable ? <IconUpdate /> : <IconCheckmark />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    <div>
                        Version <strong>{preflight?.posthog_version}</strong>
                    </div>
                    {anyUpdateAvailable && <div className="supplement">{latestVersion} is available</div>}
                </div>
                {latestVersion && (
                    <Link
                        to={`https://posthog.com/blog/the-posthog-array-${latestVersion.replace(/\./g, '-')}`}
                        target="_blank"
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
            <LemonButton icon={<IconCorporate className="text-primary" />} onClick={closeSitePopover} fullWidth>
                Instance settings
            </LemonButton>
        </Link>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconLogout />} status="stealth" fullWidth data-attr="top-menu-item-logout">
            Sign out
        </LemonButton>
    )
}

export function SitePopover(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { billingVersion } = useValues(billingLogic)
    const { isSitePopoverOpen, systemStatus } = useValues(navigationLogic)
    const { toggleSitePopover, closeSitePopover } = useActions(navigationLogic)
    const { relevantLicense } = useValues(licenseLogic)
    useMountedLogic(licenseLogic)

    const expired = relevantLicense && isLicenseExpired(relevantLicense)
    const billingV2 = billingVersion === 'v2'

    return (
        <Popover
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
                        {billingV2 || preflight?.cloud ? (
                            <LemonButton
                                onClick={closeSitePopover}
                                to={urls.organizationBilling()}
                                icon={<IconBill />}
                                fullWidth
                                data-attr="top-menu-item-billing"
                            >
                                Billing
                            </LemonButton>
                        ) : null}
                        <InviteMembersButton />
                    </SitePopoverSection>
                    {(otherOrganizations.length > 0 || preflight?.can_create_org) && (
                        <SitePopoverSection title="Other organizations">
                            {otherOrganizations.map((otherOrganization, i) => (
                                <OtherOrganizationButton
                                    key={otherOrganization.id}
                                    organization={otherOrganization}
                                    index={i + 2}
                                />
                            ))}
                            {preflight?.can_create_org && <NewOrganizationButton />}
                        </SitePopoverSection>
                    )}
                    {(!(preflight?.cloud || preflight?.demo) || user?.is_staff) && (
                        <SitePopoverSection title="PostHog instance">
                            {!preflight?.cloud && !billingV2 ? (
                                <License license={relevantLicense} expired={expired} />
                            ) : null}
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
            <div className="SitePopover__crumb" onClick={toggleSitePopover} data-attr="top-menu-toggle">
                <div
                    className="SitePopover__profile-picture"
                    title={!systemStatus ? 'Potential system issue' : expired ? 'License expired' : undefined}
                >
                    <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                    {(!systemStatus || expired) && <IconExclamation className="SitePopover__danger" />}
                </div>
                <IconArrowDropDown />
            </div>
        </Popover>
    )
}

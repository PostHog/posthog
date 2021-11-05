import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useActions, useMountedLogic, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { LemonRow } from '../../../lib/components/LemonRow'
import { IconCheckmark, IconOffline, IconPlus, IconLogout, IconUpdate, IconExclamation } from 'lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from '../../../lib/components/Link'
import { urls } from '../../../scenes/urls'
import { lemonadeLogic } from '../lemonadeLogic'
import { AvailableFeature, LicenseType, OrganizationBasicType } from '../../../types'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/logic'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { navigationLogic } from '../../navigation/navigationLogic'
import { licenseLogic } from '../../../scenes/instance/Licenses/logic'
import dayjs from 'dayjs'
import { identifierToHuman } from '../../../lib/utils'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { membershipLevelToName } from '../../../lib/utils/permissioning'

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
    const { closeSitePopover } = useActions(lemonadeLogic)

    return (
        <div className="AccountInfo">
            <ProfilePicture name={user?.first_name} email={user?.email} size="xl" />
            <div className="AccountInfo__identification SitePopover__main-info">
                <strong>{user?.first_name}</strong>
                <div className="supplement" title={user?.email}>
                    {user?.email}
                </div>
            </div>
            <Link to={urls.mySettings()} onClick={closeSitePopover} className="SitePopover__side-link">
                Manage account
            </Link>
        </div>
    )
}

function AccessLevelIndicator({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    return (
        <div className="AccessLevelIndicator" title={`Your ${organization.name} organization access level`}>
            {organization.membership_level ? membershipLevelToName.get(organization.membership_level) : '?'}
        </div>
    )
}

function CurrentOrganization({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { closeSitePopover } = useActions(lemonadeLogic)

    return (
        <LemonRow icon={<Lettermark name={organization.name} />} fullWidth>
            <>
                <div className="SitePopover__main-info SitePopover__organization">
                    <strong>{organization.name}</strong>
                    <AccessLevelIndicator organization={organization} />
                </div>
                <Link to={urls.organizationSettings()} onClick={closeSitePopover} className="SitePopover__side-link">
                    Settings
                </Link>
            </>
        </LemonRow>
    )
}

function OtherOrganizationButton({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { updateCurrentOrganization } = useActions(userLogic)

    return (
        <LemonButton
            onClick={() => updateCurrentOrganization(organization.id)}
            icon={<Lettermark name={organization.name} />}
            className="SitePopover__organization"
            type="stealth"
            title={`Switch to organization ${organization.name}`}
            fullWidth
        >
            {organization.name}
            <AccessLevelIndicator organization={organization} />
        </LemonButton>
    )
}

function InviteMembersButton(): JSX.Element {
    const { closeSitePopover, showInviteModal } = useActions(lemonadeLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() => {
                closeSitePopover()
                showInviteModal()
            }}
            fullWidth
        >
            Invite members
        </LemonButton>
    )
}

function NewOrganizationButton(): JSX.Element {
    const { closeSitePopover, showCreateOrganizationModal } = useActions(lemonadeLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() =>
                guardAvailableFeature(
                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                    'multiple organizations',
                    'Organizations group people building products together. An organization can then have multiple projects.',
                    () => {
                        closeSitePopover()
                        showCreateOrganizationModal()
                    },
                    {
                        cloud: false,
                        selfHosted: true,
                    }
                )
            }
            fullWidth
        >
            New organization
        </LemonButton>
    )
}

function License(): JSX.Element {
    const { closeSitePopover } = useActions(lemonadeLogic)
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
                <Link to={urls.instanceLicenses()} onClick={closeSitePopover} className="SitePopover__side-link">
                    Manage license
                </Link>
            </>
        </LemonRow>
    )
}

function SystemStatus(): JSX.Element {
    const { closeSitePopover } = useActions(lemonadeLogic)
    const { systemStatus } = useValues(navigationLogic) // TODO: Don't use navigationLogic in Lemonade

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
                <Link to={urls.systemStatus()} onClick={closeSitePopover} className="SitePopover__side-link">
                    System status
                </Link>
            </>
        </LemonRow>
    )
}

function Version(): JSX.Element {
    const { closeSitePopover, showChangelogModal } = useActions(lemonadeLogic)
    const { updateAvailable, latestVersion } = useValues(navigationLogic) // TODO: Don't use navigationLogic in Lemonade
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
                <Link
                    onClick={() => {
                        showChangelogModal()
                        closeSitePopover()
                    }}
                    className="SitePopover__side-link"
                >
                    Release notes
                </Link>
            </>
        </LemonRow>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconLogout />} type="stealth" fullWidth>
            Sign out
        </LemonButton>
    )
}

export function SitePopover(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { isSitePopoverOpen } = useValues(lemonadeLogic)
    const { toggleSitePopover, closeSitePopover } = useActions(lemonadeLogic)
    const { systemStatus } = useValues(navigationLogic) // TODO: Don't use navigationLogic in Lemonade
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
            <div className="SitePopover__crumb" onClick={toggleSitePopover}>
                <div
                    className="SitePopover__profile-picture"
                    title={systemStatus ? undefined : 'Potential system issue'}
                >
                    <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                    {!systemStatus && <IconExclamation className="SitePopover__danger" />}
                </div>
                <CaretDownOutlined />
            </div>
        </Popup>
    )
}

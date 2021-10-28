import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { LemonRow } from '../../../lib/components/LemonRow'
import { IconPlus, IconSignOut } from '../../../lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from '../../../lib/components/Link'
import { urls } from '../../../scenes/urls'
import { lemonadeLogic } from '../lemonadeLogic'
import { AvailableFeature, OrganizationBasicType } from '../../../types'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/logic'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { navigationLogic } from '../../navigation/navigationLogic'

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
            <div className="AccountInfo__identification">
                <div>
                    <strong>{user?.first_name}</strong>
                </div>
                <div className="supplement">{user?.email}</div>
            </div>
            <Link to={urls.mySettings()} onClick={closeSitePopover} className="SitePopover__sidelink">
                Manage account
            </Link>
        </div>
    )
}

function InitialBlob({ name }: { name?: string | null }): JSX.Element {
    const initialLetter = name ? name[0].toLocaleUpperCase() : '?'

    return <div className="InitialBlob">{initialLetter}</div>
}

function CurrentOrganizationRow({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { closeSitePopover } = useActions(lemonadeLogic)

    return (
        <LemonRow icon={<InitialBlob name={organization.name} />} fullWidth>
            <>
                <div className="CurrentOrganization">{organization.name}</div>
                <Link to={urls.organizationSettings()} onClick={closeSitePopover} className="SitePopover__sidelink">
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
            icon={<InitialBlob name={organization.name} />}
            type="stealth"
            align="start"
            title={`Switch to organization ${organization.name}`}
            fullWidth
        >
            {organization.name}
        </LemonButton>
    )
}

function NewOrganizationButton(): JSX.Element {
    const { setOrganizationModalShown } = useActions(navigationLogic) // TODO: No navigationLogic in new nav components
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
                        setOrganizationModalShown(true)
                    },
                    {
                        cloud: false,
                        selfHosted: true,
                    }
                )
            }
            align="start"
            fullWidth
        >
            New organization
        </LemonButton>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconSignOut />} type="stealth" align="start" fullWidth>
            Sign out
        </LemonButton>
    )
}

export function SitePopover(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { isSitePopoverOpen } = useValues(lemonadeLogic)
    const { toggleSitePopover } = useActions(lemonadeLogic)

    return (
        <Popup
            visible={isSitePopoverOpen}
            className="SitePopover"
            overlay={
                <>
                    <SitePopoverSection title="Signed in as">
                        <AccountInfo />
                    </SitePopoverSection>
                    <SitePopoverSection title="Current organization">
                        {currentOrganization && <CurrentOrganizationRow organization={currentOrganization} />}
                    </SitePopoverSection>
                    {(otherOrganizations.length > 0 || preflight?.can_create_org) && (
                        <SitePopoverSection title="Other organizations">
                            {otherOrganizations.map((otherOrganization) => (
                                <OtherOrganizationButton key={otherOrganization.id} organization={otherOrganization} />
                            ))}
                            {!preflight?.can_create_org && <NewOrganizationButton />}
                        </SitePopoverSection>
                    )}
                    <SitePopoverSection title="PostHog status">
                        <i>Placeholder</i>
                    </SitePopoverSection>
                    <SitePopoverSection>
                        <SignOutButton />
                    </SitePopoverSection>
                </>
            }
        >
            <div className="SitePopover__crumb" onClick={toggleSitePopover}>
                <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                <CaretDownOutlined />
            </div>
        </Popup>
    )
}

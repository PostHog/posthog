import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { IconSignOut } from '../../../lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from '../../../lib/components/Link'
import { urls } from '../../../scenes/urls'
import { lemonadeLogic } from '../lemonadeLogic'

function SitePopoverSection({ title, children }: { title?: string; children: React.ReactElement }): JSX.Element {
    return (
        <div className="SitePopover__section">
            {title && <h5 className="l5">{title}</h5>}
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
            <div>
                <Link to={urls.mySettings()} onClick={closeSitePopover} className="SitePopover__sidelink">
                    {' '}
                    Manage account
                </Link>
            </div>
        </div>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconSignOut />} style={{ justifyContent: 'start' }}>
            Sign out
        </LemonButton>
    )
}

export function SitePopover(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen } = useValues(lemonadeLogic)
    const { toggleSitePopover, closeSitePopover } = useActions(lemonadeLogic)

    return (
        <Popup
            visible={isSitePopoverOpen}
            onClickOutside={() => {
                // Don't interrupt the user if they're trying to select text
                if (!window.getSelection()?.toString()) {
                    closeSitePopover()
                }
            }}
            className="SitePopover"
            overlay={
                <>
                    <SitePopoverSection title="Signed in as">
                        <AccountInfo />
                    </SitePopoverSection>
                    <SitePopoverSection title="Current organization">
                        <i>Placeholder</i>
                    </SitePopoverSection>
                    <SitePopoverSection title="Other organizations">
                        <i>Placeholder</i>
                    </SitePopoverSection>
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

import React, { useState } from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonButton } from '../../../lib/components/LemonButton'
import { IconSignOut } from '../../../lib/components/icons'
import { Popup } from '../../../lib/components/Popup/Popup'

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconSignOut />} style={{ justifyContent: 'start' }}>
            Sign out
        </LemonButton>
    )
}

function SitePopoverSection({ title, children }: { title?: string; children: React.ReactElement }): JSX.Element {
    return (
        <div className="SitePopover__section">
            {title && <h5 className="l5">{title}</h5>}
            {children}
        </div>
    )
}

export function SitePopover(): JSX.Element {
    const { user } = useValues(userLogic)

    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popup
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            className="SitePopover"
            overlay={
                <>
                    <SitePopoverSection title="Signed in as">
                        <i>Placeholder</i>
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
            <div className="SitePopover__crumb" onClick={() => setIsOpen((state) => !state)}>
                <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                <CaretDownOutlined />
            </div>
        </Popup>
    )
}

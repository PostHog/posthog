import React from 'react'
import { CaretDownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { LemonPopover } from '../../../lib/components/LemonPopover'

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <button type="button" onClick={logout}>
            Sign out
        </button>
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

    return (
        <LemonPopover
            overlayStyle={{ width: '20rem' }}
            content={
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
            <div className="SitePopover__crumb">
                <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                <CaretDownOutlined />
            </div>
        </LemonPopover>
    )
}

import { useActions, useValues } from 'kea'
import React from 'react'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { AccountControl } from './AccountControl'
import { Announcement } from './Announcement'
import { SearchBox } from './SearchBox'
import { lemonadeLogic } from '../lemonadeLogic'
import './TopBar.scss'
import { HelpButton } from '../../../lib/components/HelpButton/HelpButton'
import { CommandPalette } from '../../../lib/components/CommandPalette'

export function TopBar(): JSX.Element {
    const { announcementMessage, isAnnouncementHidden } = useValues(lemonadeLogic)
    const { hideAnnouncement } = useActions(lemonadeLogic)

    return (
        <>
            <CommandPalette />
            {announcementMessage && (
                <Announcement
                    message={announcementMessage}
                    visible={!isAnnouncementHidden}
                    onClose={hideAnnouncement}
                />
            )}
            <header className="TopBar">
                <div className="TopBar__segment TopBar__segment--left">
                    <a href="https://posthog.com" className="TopBar__logo">
                        <FriendlyLogo />
                    </a>
                    <SearchBox />
                </div>
                <div className="TopBar__segment TopBar__segment--right">
                    <HelpButton withCaret placement="bottomRight" />
                    <AccountControl />
                </div>
            </header>
        </>
    )
}

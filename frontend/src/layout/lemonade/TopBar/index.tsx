import { useActions, useValues } from 'kea'
import React from 'react'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { AccountControl } from './AccountControl'
import { Announcement } from './Announcement'
import { SearchBox } from './SearchBox'
import { lemonadeLogic } from '../lemonadeLogic'
import './TopBar.scss'

export function TopBar(): JSX.Element {
    const { announcementMessage, isAnnouncementHidden } = useValues(lemonadeLogic)
    const { hideAnnouncement } = useActions(lemonadeLogic)

    return (
        <>
            {announcementMessage && (
                <Announcement
                    message={announcementMessage}
                    visible={!isAnnouncementHidden}
                    onClose={hideAnnouncement}
                />
            )}
            <header className="TopBar">
                <div className="TopBar__segment">
                    <FriendlyLogo />
                    <SearchBox />
                </div>
                <div className="TopBar__segment">
                    <AccountControl />
                </div>
            </header>
        </>
    )
}

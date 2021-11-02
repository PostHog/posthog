import { useActions, useValues } from 'kea'
import React from 'react'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { SitePopover } from './SitePopover'
import { Announcement } from './Announcement'
import { SearchBox } from './SearchBox'
import { lemonadeLogic } from '../lemonadeLogic'
import './index.scss'
import { HelpButton } from '../../../lib/components/HelpButton/HelpButton'
import { CommandPalette } from '../../../lib/components/CommandPalette'
import { CreateOrganizationModal } from '../../../scenes/organization/CreateOrganizationModal'
import { BulkInviteModal } from '../../../scenes/organization/Settings/BulkInviteModal'
import { ChangelogModal } from '../../ChangelogModal'

export function TopBar(): JSX.Element {
    const {
        announcementMessage,
        isAnnouncementHidden,
        isInviteModalShown,
        isCreateOrganizationModalShown,
        isChangelogModalShown,
    } = useValues(lemonadeLogic)
    const { hideAnnouncement, hideInviteModal, hideCreateOrganizationModal, hideChangelogModal } =
        useActions(lemonadeLogic)

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
                <div className="TopBar__segment TopBar__segment--left">
                    <a href="https://posthog.com" className="TopBar__logo">
                        <FriendlyLogo />
                    </a>
                    <SearchBox />
                </div>
                <div className="TopBar__segment TopBar__segment--right">
                    <HelpButton withCaret placement="bottomRight" />
                    <SitePopover />
                </div>
            </header>
            <CommandPalette />
            <ChangelogModal onDismiss={hideChangelogModal} visible={isChangelogModalShown} />
            <BulkInviteModal visible={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
        </>
    )
}

import { useActions, useValues } from 'kea'
import React from 'react'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { SitePopover } from './SitePopover'
import { Announcement } from './Announcement'
import { SearchBox } from './SearchBox'
import { navigationLogic } from '../navigationLogic'
import { HelpButton } from '../../../lib/components/HelpButton/HelpButton'
import { CommandPalette } from '../../../lib/components/CommandPalette'
import { CreateOrganizationModal } from '../../../scenes/organization/CreateOrganizationModal'
import { BulkInviteModal } from '../../../scenes/organization/Settings/BulkInviteModal'
import { Link } from '../../../lib/components/Link'
import { IconMenu, IconMenuOpen } from '../../../lib/components/icons'
import { CreateProjectModal } from '../../../scenes/project/CreateProjectModal'
import './TopBar.scss'

export function TopBar(): JSX.Element {
    const {
        isSideBarShown,
        bareNav,
        announcementMessage,
        isAnnouncementShown,
        isInviteModalShown,
        isCreateOrganizationModalShown,
        isCreateProjectModalShown,
    } = useValues(navigationLogic)
    const { toggleSideBar, hideAnnouncement, hideInviteModal, hideCreateOrganizationModal, hideCreateProjectModal } =
        useActions(navigationLogic)

    return (
        <>
            {announcementMessage && (
                <Announcement message={announcementMessage} visible={isAnnouncementShown} onClose={hideAnnouncement} />
            )}
            <header className="TopBar">
                <div className="TopBar__segment TopBar__segment--left">
                    {!bareNav && (
                        <div className="TopBar__hamburger" onClick={toggleSideBar}>
                            {isSideBarShown ? <IconMenuOpen /> : <IconMenu />}
                        </div>
                    )}
                    <Link to="/" className="TopBar__logo">
                        <FriendlyLogo />
                    </Link>
                    <SearchBox />
                </div>
                <div className="TopBar__segment TopBar__segment--right">
                    <HelpButton />
                    <SitePopover />
                </div>
            </header>
            <CommandPalette />
            <BulkInviteModal visible={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
        </>
    )
}

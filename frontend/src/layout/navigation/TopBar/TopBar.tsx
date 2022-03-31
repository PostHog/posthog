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
import { InviteModal } from '../../../scenes/organization/Settings/InviteModal'
import { Link } from '../../../lib/components/Link'
import { IconMenu, IconMenuOpen } from '../../../lib/components/icons'
import { CreateProjectModal } from '../../../scenes/project/CreateProjectModal'
import './TopBar.scss'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { UniversalSearchPopup } from 'lib/components/UniversalSearch/UniversalSearchPopup'
import { UniversalSearchGroupType } from 'lib/components/UniversalSearch/types'

export function TopBar(): JSX.Element {
    const { isSideBarShown, bareNav, mobileLayout, isCreateOrganizationModalShown, isCreateProjectModalShown } =
        useValues(navigationLogic)
    const { toggleSideBarBase, toggleSideBarMobile, hideCreateOrganizationModal, hideCreateProjectModal } =
        useActions(navigationLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)

    return (
        <>
            <Announcement />
            <header className="TopBar">
                <div className="TopBar__segment TopBar__segment--left">
                    {!bareNav && (
                        <div
                            className="TopBar__hamburger"
                            onClick={mobileLayout ? toggleSideBarMobile : toggleSideBarBase}
                        >
                            {isSideBarShown ? <IconMenuOpen /> : <IconMenu />}
                        </div>
                    )}
                    <Link to="/" className="TopBar__logo">
                        <FriendlyLogo />
                    </Link>
                    <div>
                        <UniversalSearchPopup
                            groupType={UniversalSearchGroupType.Events}
                            groupTypes={[
                                UniversalSearchGroupType.Events,
                                UniversalSearchGroupType.Persons,
                                UniversalSearchGroupType.Actions,
                                UniversalSearchGroupType.Cohorts,
                                UniversalSearchGroupType.Insights,
                                UniversalSearchGroupType.FeatureFlags,
                                UniversalSearchGroupType.Plugins,
                                UniversalSearchGroupType.Experiments,
                                UniversalSearchGroupType.Dashboards,
                                // UniversalSearchGroupType.GroupsPrefix,
                                'groups_0',
                                'groups_1',
                                // // 'groups_2',
                            ]}
                        />
                    </div>
                    <SearchBox />
                </div>
                <div className="TopBar__segment TopBar__segment--right">
                    <HelpButton />
                    <SitePopover />
                </div>
            </header>
            <CommandPalette />
            <InviteModal visible={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
        </>
    )
}

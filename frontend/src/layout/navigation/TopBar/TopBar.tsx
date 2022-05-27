import { useActions, useValues } from 'kea'
import React from 'react'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { SitePopover } from './SitePopover'
import { Announcement } from './Announcement'
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
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'

export function TopBar(): JSX.Element {
    const { isSideBarShown, bareNav, mobileLayout, isCreateOrganizationModalShown, isCreateProjectModalShown } =
        useValues(navigationLogic)
    const { toggleSideBarBase, toggleSideBarMobile, hideCreateOrganizationModal, hideCreateProjectModal } =
        useActions(navigationLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { groupNamesTaxonomicTypes } = useValues(groupsModel)

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

                    <div style={{ flexGrow: 1 }}>
                        <UniversalSearchPopup
                            groupType={TaxonomicFilterGroupType.Events}
                            groupTypes={[
                                TaxonomicFilterGroupType.Events,
                                TaxonomicFilterGroupType.Actions,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.Insights,
                                TaxonomicFilterGroupType.FeatureFlags,
                                TaxonomicFilterGroupType.Plugins,
                                TaxonomicFilterGroupType.Experiments,
                                TaxonomicFilterGroupType.Dashboards,
                                ...groupNamesTaxonomicTypes,
                            ]}
                        />
                    </div>
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

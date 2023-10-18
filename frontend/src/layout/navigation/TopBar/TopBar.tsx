import { useActions, useValues } from 'kea'
import { Logo } from '~/toolbar/assets/Logo'
import { SitePopover } from './SitePopover'
import { Announcement } from './Announcement'
import { navigationLogic } from '../navigationLogic'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { CommandPalette } from 'lib/components/CommandPalette'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { InviteModal } from 'scenes/organization/Settings/InviteModal'
import { Link } from 'lib/lemon-ui/Link'
import { IconMenu, IconMenuOpen } from 'lib/lemon-ui/icons'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import './TopBar.scss'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { UniversalSearchPopover } from 'lib/components/UniversalSearch/UniversalSearchPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { NotificationBell } from '~/layout/navigation/TopBar/NotificationBell'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import ActivationSidebarToggle from 'lib/components/ActivationSidebar/ActivationSidebarToggle'
import { NotebookButton } from '~/layout/navigation/TopBar/NotebookButton'

export function TopBar(): JSX.Element {
    const {
        isSideBarShown,
        noSidebar,
        minimalTopBar,
        mobileLayout,
        isCreateOrganizationModalShown,
        isCreateProjectModalShown,
    } = useValues(navigationLogic)
    const { toggleSideBarBase, toggleSideBarMobile, hideCreateOrganizationModal, hideCreateProjectModal } =
        useActions(navigationLogic)
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { groupNamesTaxonomicTypes } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasNotebooks = !!featureFlags[FEATURE_FLAGS.NOTEBOOKS]

    const groupTypes = [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Persons,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Insights,
        TaxonomicFilterGroupType.FeatureFlags,
        TaxonomicFilterGroupType.Plugins,
        TaxonomicFilterGroupType.Experiments,
        TaxonomicFilterGroupType.Dashboards,
        ...groupNamesTaxonomicTypes,
    ]

    if (hasNotebooks) {
        groupTypes.push(TaxonomicFilterGroupType.Notebooks)
    }

    return (
        <>
            <Announcement />
            <header className="TopBar">
                <div className="TopBar__segment TopBar__segment--left">
                    {!noSidebar && (
                        <div
                            className="TopBar__hamburger"
                            onClick={() => (mobileLayout ? toggleSideBarMobile() : toggleSideBarBase())}
                        >
                            {isSideBarShown ? <IconMenuOpen /> : <IconMenu />}
                        </div>
                    )}
                    <Link to="/" className="TopBar__logo">
                        <Logo />
                    </Link>
                    {!minimalTopBar && (
                        <>
                            <div className="grow">
                                <UniversalSearchPopover
                                    groupType={TaxonomicFilterGroupType.Events}
                                    groupTypes={groupTypes}
                                />
                            </div>
                            <ActivationSidebarToggle />
                        </>
                    )}
                </div>
                <div className="TopBar__segment TopBar__segment--right">
                    {!minimalTopBar && (
                        <>
                            {hasNotebooks && <NotebookButton />}
                            <NotificationBell />
                        </>
                    )}
                    <HelpButton />
                    <SitePopover />
                </div>
            </header>
            <CommandPalette />
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <CreateOrganizationModal isVisible={isCreateOrganizationModalShown} onClose={hideCreateOrganizationModal} />
            <CreateProjectModal isVisible={isCreateProjectModalShown} onClose={hideCreateProjectModal} />
        </>
    )
}

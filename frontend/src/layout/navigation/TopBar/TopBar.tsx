import { useActions, useValues } from 'kea'
import { Logo } from '~/toolbar/assets/Logo'
import { SitePopover } from './SitePopover'
import { Announcement } from './Announcement'
import { navigationLogic } from '../navigationLogic'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { Link } from 'lib/lemon-ui/Link'
import { IconMenu, IconMenuOpen } from 'lib/lemon-ui/icons'
import './TopBar.scss'
import { UniversalSearchPopover } from 'lib/components/UniversalSearch/UniversalSearchPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { NotificationBell } from '~/layout/navigation/TopBar/NotificationBell'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { NotebookButton } from '~/layout/navigation/TopBar/NotebookButton'
import { ActivationSidebarToggle } from 'lib/components/ActivationSidebar/ActivationSidebarToggle'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonButtonWithDropdown, Lettermark } from '@posthog/lemon-ui'
import { ProjectSwitcherOverlay } from '../ProjectSwitcher'
import { topBarLogic } from './topBarLogic'

export function TopBar(): JSX.Element {
    const { isSideBarShown, noSidebar, minimalTopBar, mobileLayout } = useValues(navigationLogic)
    const { toggleSideBarBase, toggleSideBarMobile } = useActions(navigationLogic)
    const { groupNamesTaxonomicTypes } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(topBarLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(topBarLogic)

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
                    {!minimalTopBar ? (
                        <>
                            {hasNotebooks && <NotebookButton />}
                            <NotificationBell />
                        </>
                    ) : (
                        currentOrganization?.teams &&
                        currentOrganization.teams.length > 1 && (
                            <div>
                                <LemonButtonWithDropdown
                                    icon={<Lettermark name={currentOrganization?.name} />}
                                    onClick={() => toggleProjectSwitcher()}
                                    dropdown={{
                                        visible: isProjectSwitcherShown,
                                        onClickOutside: hideProjectSwitcher,
                                        overlay: <ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />,
                                        actionable: true,
                                        placement: 'top-end',
                                    }}
                                    type="secondary"
                                    fullWidth
                                >
                                    <span className="text-muted">Switch project</span>
                                </LemonButtonWithDropdown>
                            </div>
                        )
                    )}
                    <HelpButton />
                    <SitePopover />
                </div>
            </header>
            <CommandPalette />
        </>
    )
}

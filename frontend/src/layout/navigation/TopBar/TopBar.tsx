import './TopBar.scss'

import { LemonButtonWithDropdown, Lettermark } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivationSidebarToggle } from 'lib/components/ActivationSidebar/ActivationSidebarToggle'
import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { UniversalSearchPopover } from 'lib/components/UniversalSearch/UniversalSearchPopover'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconMenu, IconMenuOpen } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { NotebookButton } from '~/layout/navigation/TopBar/NotebookButton'
import { YearInHogButton } from '~/layout/navigation/TopBar/YearInHogButton'
import { NotificationBell } from '~/layout/navigation-3000/sidepanel/panels/activity/NotificationBell'
import { groupsModel } from '~/models/groupsModel'
import { Logo } from '~/toolbar/assets/Logo'

import { navigationLogic } from '../navigationLogic'
import { ProjectSwitcherOverlay } from '../ProjectSwitcher'
import { Announcement } from './Announcement'
import { SitePopover } from './SitePopover'
import { topBarLogic } from './topBarLogic'

export function TopBar(): JSX.Element {
    const { isSideBarShown, noSidebar, minimalTopBar, mobileLayout } = useValues(navigationLogic)
    const { toggleSideBarBase, toggleSideBarMobile } = useActions(navigationLogic)
    const { groupNamesTaxonomicTypes } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(topBarLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(topBarLogic)

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
        TaxonomicFilterGroupType.Notebooks,
        ...groupNamesTaxonomicTypes,
    ]

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
                            {!!featureFlags[FEATURE_FLAGS.YEAR_IN_HOG] &&
                                window.POSTHOG_APP_CONTEXT?.year_in_hog_url && (
                                    <YearInHogButton
                                        url={`${window.location.origin}${window.POSTHOG_APP_CONTEXT.year_in_hog_url}`}
                                    />
                                )}
                            <NotebookButton />
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

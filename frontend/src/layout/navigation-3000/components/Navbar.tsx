import { useActions, useValues } from 'kea'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import {
    IconApps,
    IconBarChart,
    IconCohort,
    IconComment,
    IconCottage,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconHelpOutline,
    IconLive,
    IconPerson,
    IconRecording,
    IconSettings,
    IconUnverifiedEvent,
} from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SitePopoverOverlay } from '~/layout/navigation/TopBar/SitePopover'
import { NavbarButton } from './NavbarButton'

export function Navbar(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover } = useActions(navigationLogic)

    return (
        <nav className="Navbar3000">
            <div className="Navbar3000__content">
                <div className="Navbar3000__top">
                    <ul>
                        <NavbarButton
                            identifier={Scene.ProjectHomepage}
                            icon={<IconCottage />}
                            to={urls.projectHomepage()}
                        />
                        <NavbarButton icon={<IconGauge />} identifier={Scene.Dashboards} to={urls.dashboards()} />
                        <NavbarButton
                            icon={<IconBarChart />}
                            identifier={Scene.SavedInsights}
                            to={urls.savedInsights()}
                        />
                        <NavbarButton
                            icon={<IconRecording />}
                            identifier={Scene.SessionRecordings}
                            to={urls.sessionRecordings()}
                        />
                        <NavbarButton icon={<IconFlag />} identifier={Scene.FeatureFlags} to={urls.featureFlags()} />
                        <NavbarButton
                            icon={<IconExperiment />}
                            identifier={Scene.Experiments}
                            to={urls.experiments()}
                        />
                    </ul>
                    <ul>
                        <NavbarButton icon={<IconLive />} identifier={Scene.Events} to={urls.events()} />
                        <NavbarButton
                            icon={<IconUnverifiedEvent />}
                            identifier={Scene.DataManagement}
                            to={urls.eventDefinitions()}
                        />
                        <NavbarButton icon={<IconPerson />} identifier={Scene.Persons} to={urls.persons()} />
                        <NavbarButton icon={<IconCohort />} identifier={Scene.Cohorts} to={urls.cohorts()} />
                        <NavbarButton icon={<IconComment />} identifier={Scene.Annotations} to={urls.annotations()} />
                        <NavbarButton icon={<IconApps />} identifier={Scene.Plugins} to={urls.projectApps()} />
                    </ul>
                </div>
                <div className="Navbar3000__bottom">
                    <ul>
                        <HelpButton
                            customComponent={
                                <NavbarButton
                                    icon={<IconHelpOutline />}
                                    identifier="help-button"
                                    title="Need any help?"
                                />
                            }
                            placement="right-end"
                        />
                        <NavbarButton
                            icon={<IconSettings />}
                            identifier={Scene.ProjectSettings}
                            to={urls.projectSettings()}
                        />
                        <Popover
                            overlay={<SitePopoverOverlay />}
                            visible={isSitePopoverOpen}
                            onClickOutside={closeSitePopover}
                            placement="right-end"
                        >
                            <NavbarButton
                                icon={<ProfilePicture name={user?.first_name} email={user?.email} size="md" />}
                                identifier="me"
                                title={`Hi${user?.first_name ? `, ${user?.first_name}` : ''}!`}
                                onClick={toggleSitePopover}
                            />
                        </Popover>
                    </ul>
                </div>
            </div>
        </nav>
    )
}

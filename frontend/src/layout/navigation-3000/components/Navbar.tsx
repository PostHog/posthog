import { LemonBadge } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconQuestion, IconGear, IconDay, IconNight, IconAsterisk } from '@posthog/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SitePopoverOverlay } from '~/layout/navigation/TopBar/SitePopover'
import { navigation3000Logic } from '../navigationLogic'
import { themeLogic } from '../themeLogic'
import { NavbarButton } from './NavbarButton'
import { urls } from 'scenes/urls'

export function Navbar(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover } = useActions(navigationLogic)
    const { isSidebarShown, activeNavbarItemId, navbarItems } = useValues(navigation3000Logic)
    const { showSidebar, hideSidebar } = useActions(navigation3000Logic)
    const { isDarkModeOn, darkModeSavedPreference, darkModeSystemPreference, isThemeSyncedWithSystem } =
        useValues(themeLogic)
    const { toggleTheme } = useActions(themeLogic)

    const activeThemeIcon = isDarkModeOn ? <IconNight /> : <IconDay />

    return (
        <nav className="Navbar3000">
            <div className="Navbar3000__content">
                <div className="Navbar3000__top">
                    {navbarItems.map((section, index) => (
                        <ul key={index}>
                            {section.map((item) => (
                                <NavbarButton
                                    key={item.identifier}
                                    title={item.label}
                                    identifier={item.identifier}
                                    icon={item.icon}
                                    to={'to' in item ? item.to : undefined}
                                    onClick={
                                        'logic' in item
                                            ? () => {
                                                  if (activeNavbarItemId === item.identifier && isSidebarShown) {
                                                      hideSidebar()
                                                  } else {
                                                      showSidebar(item.identifier)
                                                  }
                                              }
                                            : undefined
                                    }
                                    active={activeNavbarItemId === item.identifier && isSidebarShown}
                                />
                            ))}
                        </ul>
                    ))}
                </div>
                <div className="Navbar3000__bottom">
                    <ul>
                        <NavbarButton
                            icon={
                                isThemeSyncedWithSystem ? (
                                    <div className="relative">
                                        {activeThemeIcon}
                                        <LemonBadge size="small" position="top-right" content={<IconAsterisk />} />
                                    </div>
                                ) : (
                                    activeThemeIcon
                                )
                            }
                            identifier="theme-button"
                            title={
                                darkModeSavedPreference === false
                                    ? `Sync theme with system preference (${
                                          darkModeSystemPreference ? 'dark' : 'light'
                                      } mode)`
                                    : darkModeSavedPreference
                                    ? 'Switch to light mode'
                                    : 'Switch to dark mode'
                            }
                            onClick={() => toggleTheme()}
                            persistentTooltip
                        />
                        <HelpButton
                            customComponent={
                                <NavbarButton
                                    icon={<IconQuestion />}
                                    identifier="help-button"
                                    title="Need any help?"
                                    popoverMarker
                                />
                            }
                            placement="right-end"
                        />
                        <NavbarButton
                            icon={<IconGear />}
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
                                popoverMarker
                            />
                        </Popover>
                    </ul>
                </div>
            </div>
        </nav>
    )
}

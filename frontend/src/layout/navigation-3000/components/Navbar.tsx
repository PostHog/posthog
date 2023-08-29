import { LemonBadge } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconDarkMode, IconHelpOutline, IconLightMode, IconSettings, IconSync } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SitePopoverOverlay } from '~/layout/navigation/TopBar/SitePopover'
import { navigation3000Logic } from '../navigationLogic'
import { NAVBAR_ITEMS } from '../navbarItems'
import { themeLogic } from '../themeLogic'
import { NavbarButton } from './NavbarButton'
import { urls } from 'scenes/urls'
import { sceneLogic } from 'scenes/sceneLogic'

export function Navbar(): JSX.Element {
    const { user } = useValues(userLogic)
    const { aliasedActiveScene } = useValues(sceneLogic)
    const { isSitePopoverOpen } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover } = useActions(navigationLogic)
    const { isSidebarShown, activeNavbarItemId } = useValues(navigation3000Logic)
    const { showSidebar, hideSidebar } = useActions(navigation3000Logic)
    const { isDarkModeOn, darkModeSavedPreference, darkModeSystemPreference, isThemeSyncedWithSystem } =
        useValues(themeLogic)
    const { toggleTheme } = useActions(themeLogic)

    const activeThemeIcon = isDarkModeOn ? <IconDarkMode /> : <IconLightMode />

    return (
        <nav className="Navbar3000">
            <div className="Navbar3000__content">
                <div className="Navbar3000__top">
                    {NAVBAR_ITEMS.map((section, index) => (
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
                                    here={aliasedActiveScene === item.identifier}
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
                                        <LemonBadge size="small" position="top-right" content={<IconSync />} />
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

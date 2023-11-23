import { IconAsterisk, IconDay, IconGear, IconNight, IconSearch } from '@posthog/icons'
import { LemonBadge } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useRef } from 'react'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SitePopoverOverlay } from '~/layout/navigation/TopBar/SitePopover'

import { navigation3000Logic } from '../navigationLogic'
import { themeLogic } from '../themeLogic'
import { NavbarButton } from './NavbarButton'

export function ThemeIcon(): JSX.Element {
    const { isDarkModeOn, isThemeSyncedWithSystem } = useValues(themeLogic)

    const activeThemeIcon = isDarkModeOn ? <IconNight /> : <IconDay />

    return isThemeSyncedWithSystem ? (
        <div className="relative">
            {activeThemeIcon}
            <LemonBadge size="small" position="top-right" content={<IconAsterisk />} />
        </div>
    ) : (
        activeThemeIcon
    )
}

export function Navbar(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover } = useActions(navigationLogic)
    const { isSidebarShown, activeNavbarItemId, navbarItems } = useValues(navigation3000Logic)
    const { showSidebar, hideSidebar, toggleNavCollapsed } = useActions(navigation3000Logic)
    const { darkModeSavedPreference, darkModeSystemPreference } = useValues(themeLogic)
    const { toggleTheme } = useActions(themeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)

    const containerRef = useRef<HTMLDivElement | null>(null)

    return (
        <nav className="Navbar3000" ref={containerRef}>
            <div className="Navbar3000__content">
                <div className="Navbar3000__top">
                    {navbarItems.map((section, index) => (
                        <ul key={index}>
                            {section.map((item) =>
                                item.featureFlag && !featureFlags[item.featureFlag] ? null : (
                                    <NavbarButton
                                        key={item.identifier}
                                        title={item.label}
                                        identifier={item.identifier}
                                        icon={item.icon}
                                        tag={item.tag}
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
                                )
                            )}
                        </ul>
                    ))}
                </div>
                <div className="Navbar3000__bottom">
                    <ul>
                        <NavbarButton
                            identifier="search-button"
                            icon={<IconSearch />}
                            title="Search"
                            onClick={toggleSearchBar}
                            keyboardShortcut={{ command: true, k: true }}
                        />
                        <NavbarButton
                            icon={<ThemeIcon />}
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
                            shortTitle="Toggle theme"
                            onClick={() => toggleTheme()}
                            persistentTooltip
                        />
                        <NavbarButton
                            icon={<IconGear />}
                            identifier={Scene.Settings}
                            title="Project settings"
                            to={urls.settings('project')}
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
                                shortTitle={user?.first_name || user?.email}
                                onClick={toggleSitePopover}
                            />
                        </Popover>
                    </ul>
                </div>
            </div>
            <Resizer
                placement={'right'}
                containerRef={containerRef}
                closeThreshold={100}
                onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                onDoubleClick={() => toggleNavCollapsed()}
            />
        </nav>
    )
}

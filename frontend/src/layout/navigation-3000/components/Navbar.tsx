import { IconGear, IconSearch, IconToolbar } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { IconWarning } from 'lib/lemon-ui/icons'
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
import { NavbarButton } from './NavbarButton'

export function Navbar(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen, systemStatusHealthy } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover } = useActions(navigationLogic)
    const { isNavShown, isSidebarShown, activeNavbarItemId, navbarItems, mobileLayout } = useValues(navigation3000Logic)
    const { showSidebar, hideSidebar, toggleNavCollapsed, hideNavOnMobile } = useActions(navigation3000Logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)

    const containerRef = useRef<HTMLDivElement | null>(null)

    return (
        <>
            <nav className={clsx('Navbar3000', !isNavShown && 'Navbar3000--hidden')} ref={containerRef}>
                <div className="Navbar3000__content">
                    <ScrollableShadows innerClassName="Navbar3000__top" direction="vertical">
                        {navbarItems.map((section, index) => (
                            <ul key={index}>
                                {section.map((item) =>
                                    item.featureFlag && !featureFlags[item.featureFlag] ? null : (
                                        <NavbarButton
                                            key={item.identifier}
                                            title={item.label}
                                            identifier={item.identifier}
                                            icon={item.icon}
                                            sideAction={item.sideAction}
                                            tag={item.tag}
                                            to={'to' in item ? item.to : undefined}
                                            onClick={
                                                'logic' in item
                                                    ? () => {
                                                          if (
                                                              activeNavbarItemId === item.identifier &&
                                                              isSidebarShown
                                                          ) {
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
                    </ScrollableShadows>
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
                                icon={<IconToolbar />}
                                identifier={Scene.ToolbarLaunch}
                                title="Toolbar"
                                to={urls.toolbarLaunch()}
                            />
                            <NavbarButton
                                icon={<IconGear />}
                                identifier={Scene.Settings}
                                title="Settings"
                                to={urls.settings('project')}
                            />

                            {!systemStatusHealthy ? (
                                <NavbarButton
                                    icon={<IconWarning />}
                                    identifier={Scene.Settings}
                                    title="System issue!"
                                    to={urls.instanceStatus()}
                                />
                            ) : null}

                            <Popover
                                overlay={<SitePopoverOverlay />}
                                visible={isSitePopoverOpen}
                                onClickOutside={closeSitePopover}
                                placement="right-end"
                                className="min-w-70"
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
                {!mobileLayout && (
                    <Resizer
                        placement={'right'}
                        containerRef={containerRef}
                        closeThreshold={100}
                        onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                        onDoubleClick={() => toggleNavCollapsed()}
                    />
                )}
            </nav>
            {mobileLayout && (
                <div
                    className={clsx('Navbar3000__overlay', !isNavShown && 'Navbar3000--hidden')}
                    onClick={() => hideNavOnMobile()}
                />
            )}
        </>
    )
}

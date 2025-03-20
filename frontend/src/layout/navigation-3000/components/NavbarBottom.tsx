import { IconGear, IconSearch, IconToolbar, IconWarning } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { DebugNotice } from 'lib/components/DebugNotice'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccountPopoverOverlay } from '~/layout/navigation/TopBar/AccountPopover'
import { SidePanelTab } from '~/types'

import { SidePanelActivationIcon } from '../sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'
import { KeyboardShortcut } from './KeyboardShortcut'
import { NavbarButton } from './NavbarButton'

export function NavbarBottom(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen, systemStatusHealthy } = useValues(navigationLogic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { visibleTabs, sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    return (
        <div className="Navbar3000__bottom">
            <ul>
                <DebugNotice />
                {visibleTabs.includes(SidePanelTab.Activation) && (
                    <NavbarButton
                        identifier="activation-button"
                        icon={<SidePanelActivationIcon />}
                        title="Quick start"
                        onClick={() =>
                            sidePanelOpen && selectedTab === SidePanelTab.Activation
                                ? closeSidePanel()
                                : openSidePanel(SidePanelTab.Activation)
                        }
                    />
                )}
                <NavbarButton
                    identifier="search-button"
                    icon={<IconSearch />}
                    shortTitle="Search"
                    title={
                        <div className="flex flex-col gap-0.5">
                            <span>
                                For search, press <KeyboardShortcut command k />
                            </span>
                            <span>
                                For commands, press <KeyboardShortcut command shift k />
                            </span>
                        </div>
                    }
                    forceTooltipOnHover
                    sideIcon={<KeyboardShortcut command k />}
                    onClick={toggleSearchBar}
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
                    to={urls.settings(user?.organization?.id ? 'project' : 'user-danger-zone')}
                />

                {!systemStatusHealthy ? (
                    <NavbarButton
                        icon={<IconWarning />}
                        identifier={Scene.SystemStatus}
                        title="System issue!"
                        to={urls.instanceStatus()}
                    />
                ) : null}

                <Popover
                    overlay={<AccountPopoverOverlay />}
                    visible={isAccountPopoverOpen}
                    onClickOutside={closeAccountPopover}
                    placement="right-end"
                    className="min-w-70"
                >
                    <NavbarButton
                        icon={<ProfilePicture user={user} size="md" />}
                        identifier="me"
                        title={`Hi${user?.first_name ? `, ${user?.first_name}` : ''}!`}
                        shortTitle={user?.first_name || user?.email}
                        onClick={toggleAccountPopover}
                    />
                </Popover>
            </ul>
        </div>
    )
}

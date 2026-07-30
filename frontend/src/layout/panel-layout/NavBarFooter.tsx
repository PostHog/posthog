import { useActions, useValues } from 'kea'

import { IconGear, IconSearch } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { DebugNotice } from 'lib/components/DebugNotice'
import { HelpMenu } from 'lib/components/HelpMenu/HelpMenu'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { NotificationsMenu } from 'lib/components/NotificationsMenu/NotificationsMenu'
import { PosthogStatusShownOnlyIfNotOperational } from 'lib/components/PosthogStatus/PosthogStatusShownOnlyIfNotOperational'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { InstallationStatusNavButton } from './InstallationStatusNavButton'

export function NavBarFooter({ isLayoutNavCollapsed }: { isLayoutNavCollapsed: boolean }): JSX.Element {
    const isNotificationsEnabled = useFeatureFlag('REAL_TIME_NOTIFICATIONS')
    const { featureFlags } = useValues(featureFlagLogic)
    const { toggleCommand } = useActions(commandLogic)
    const showSearchHint = featureFlags[FEATURE_FLAGS.CMD_K_NAV_EXPERIMENT] === 'footer-hint'

    return (
        <div className="p-1 flex flex-col gap-px items-start pb-2">
            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                <DebugNotice isCollapsed={isLayoutNavCollapsed} />
            </div>

            <NavPanelAdvertisement />

            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                {showSearchHint && (
                    <ButtonPrimitive
                        menuItem={!isLayoutNavCollapsed}
                        iconOnly={isLayoutNavCollapsed}
                        data-attr="nav-footer-search-hint"
                        tooltip={
                            isLayoutNavCollapsed ? (
                                <div className="flex items-center gap-2">
                                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                                </div>
                            ) : undefined
                        }
                        tooltipPlacement="right"
                        onClick={() => {
                            posthog.capture('nav search clicked')
                            toggleCommand('nav-footer-hint')
                        }}
                    >
                        <IconSearch />
                        {!isLayoutNavCollapsed && (
                            <>
                                <span className="flex-1 text-left">Search</span>
                                <RenderKeybind keybind={[keyBinds.search]} />
                            </>
                        )}
                    </ButtonPrimitive>
                )}
                {isNotificationsEnabled && <NotificationsMenu iconOnly={isLayoutNavCollapsed} />}
                <InstallationStatusNavButton iconOnly={isLayoutNavCollapsed} />
                <Link
                    to={urls.settings('project')}
                    buttonProps={{ menuItem: isLayoutNavCollapsed ? false : true }}
                    tooltip={isLayoutNavCollapsed ? 'Settings' : undefined}
                    tooltipPlacement="right"
                    data-attr="navbar-settings"
                >
                    <IconGear />
                    {!isLayoutNavCollapsed && 'Settings'}
                </Link>
                <HelpMenu iconOnly={isLayoutNavCollapsed} />
                <PosthogStatusShownOnlyIfNotOperational iconOnly={isLayoutNavCollapsed} />
            </div>
        </div>
    )
}

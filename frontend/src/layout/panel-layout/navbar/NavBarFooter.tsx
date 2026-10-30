import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { DebugNotice } from 'lib/components/DebugNotice'
import { HelpMenu } from 'lib/components/HelpMenu/HelpMenu'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { NotificationsMenu } from 'lib/components/NotificationsMenu/NotificationsMenu'
import { PosthogStatusShownOnlyIfNotOperational } from 'lib/components/PosthogStatus/PosthogStatusShownOnlyIfNotOperational'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { WizardRunSidebarWidget } from 'products/wizard/frontend/views/run-sidebar/WizardRunSidebarWidget'

import { PostHogTeamCohortBanner } from './PostHogTeamCohortBanner'

export function NavBarFooter({ isLayoutNavCollapsed }: { isLayoutNavCollapsed: boolean }): JSX.Element {
    const isNotificationsEnabled = useFeatureFlag('REAL_TIME_NOTIFICATIONS')
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')
    const { currentProjectId } = useValues(projectLogic)

    return (
        <div className="p-1 flex flex-col gap-px items-start pb-2">
            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                <DebugNotice isCollapsed={isLayoutNavCollapsed} />
                <PostHogTeamCohortBanner isCollapsed={isLayoutNavCollapsed} />
            </div>

            <NavPanelAdvertisement />

            {wizardUiEnabled && !isLayoutNavCollapsed && currentProjectId !== null && (
                <div className="w-full pb-1">
                    <WizardRunSidebarWidget projectId={String(currentProjectId)} />
                </div>
            )}

            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                {isNotificationsEnabled && <NotificationsMenu iconOnly={isLayoutNavCollapsed} />}
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

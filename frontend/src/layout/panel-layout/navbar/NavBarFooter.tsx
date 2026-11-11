import { useValues } from 'kea'
import { Suspense } from 'react'

import { IconGear } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { PostHogErrorBoundary } from '@posthog/react'

import { DebugNotice } from 'lib/components/DebugNotice'
import { HelpMenu } from 'lib/components/HelpMenu/HelpMenu'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { NotificationsMenu } from 'lib/components/NotificationsMenu/NotificationsMenu'
import { PosthogStatusShownOnlyIfNotOperational } from 'lib/components/PosthogStatus/PosthogStatusShownOnlyIfNotOperational'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { PostHogTeamCohortBanner } from './PostHogTeamCohortBanner'

// Flag-gated, so users without the flag skip the wizard chunk on every page.
const WizardRunSidebarWidget = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRunSidebarWidget').then(({ WizardRunSidebarWidget }) => ({
        default: WizardRunSidebarWidget,
    }))
)

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
                    {/* A local boundary keeps a failed widget chunk from reaching the shell's
                        ChunkLoadErrorBoundary, which reloads the whole app. */}
                    <PostHogErrorBoundary fallback={<></>}>
                        <Suspense fallback={null}>
                            <WizardRunSidebarWidget projectId={String(currentProjectId)} />
                        </Suspense>
                    </PostHogErrorBoundary>
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

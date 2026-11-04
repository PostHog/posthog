import { useActions, useValues } from 'kea'
import { Suspense, useState } from 'react'

import { IconEllipsis, IconExternal, IconWarning } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'
import { PostHogErrorBoundary } from '@posthog/react'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { todayMenuLinkItem } from './todayMenuLinkItem'
import { SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'
import { TodayRailTile } from './TodayRailTile'

// Flag-gated, so users without the flag skip the wizard chunk.
const WizardRunsUnseenDot = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRunsUnseenDot').then(({ WizardRunsUnseenDot }) => ({
        default: WizardRunsUnseenDot,
    }))
)
const WizardRunsMoreMenuItem = lazyWithRetry(() =>
    import('products/wizard/frontend/views/run-sidebar/WizardRunsMoreMenuItem').then(({ WizardRunsMoreMenuItem }) => ({
        default: WizardRunsMoreMenuItem,
    }))
)

/**
 * The rail's "More" menu. The help menu shortcut opens it too.
 * Its `data-attr`s are pinned: they match the classic help menu, so autocapture data stays continuous.
 */
export function TodayMoreMenu(): JSX.Element {
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { statusPageUrl } = useValues(posthogStatusLogic)
    const { statusSeverity, statusText, healthSeverity, healthText, moreSeverity, moreLabel } =
        useValues(todayRailStatusLogic)
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')
    const { currentProjectId } = useValues(projectLogic)
    const [hasUnseenWizardRuns, setHasUnseenWizardRuns] = useState(false)

    return (
        <DropdownMenu open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <DropdownMenuTrigger
                render={
                    <TodayRailTile
                        label="More"
                        icon={
                            <>
                                {statusSeverity === 'ok' ? (
                                    <IconEllipsis />
                                ) : (
                                    <IconWarning className={SEVERITY_TEXT_CLASS[statusSeverity]} />
                                )}
                                {wizardUiEnabled &&
                                    currentProjectId !== null && (
                                        // A local boundary keeps a failed wizard chunk from reaching the shell's
                                        // ChunkLoadErrorBoundary, which reloads the whole app.
                                        <PostHogErrorBoundary fallback={<></>}>
                                            <Suspense fallback={null}>
                                                <WizardRunsUnseenDot
                                                    projectId={String(currentProjectId)}
                                                    onUnseenChange={setHasUnseenWizardRuns}
                                                />
                                            </Suspense>
                                        </PostHogErrorBoundary>
                                    )}
                            </>
                        }
                        active={isHelpMenuOpen}
                        dataAttr="help-menu-button"
                        severity={moreSeverity}
                        aria-label={hasUnseenWizardRuns ? `${moreLabel}, new Wizard runs` : moreLabel}
                    />
                }
            />
            <DropdownMenuContent side="right" align="end" className="w-56">
                <DropdownMenuItem
                    render={todayMenuLinkItem(statusPageUrl, { external: true })}
                    description={
                        statusText && <span className={SEVERITY_TEXT_CLASS[statusSeverity]}>{statusText}</span>
                    }
                    data-attr="more-menu-status-button"
                >
                    Status page
                    <IconExternal data-icon="inline-end" className="ms-auto" />
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.health())}
                    description={
                        healthText && (
                            <span className={SEVERITY_TEXT_CLASS[healthSeverity === 'ok' ? 'none' : healthSeverity]}>
                                {healthText}
                            </span>
                        )
                    }
                    data-attr="more-menu-health-button"
                >
                    Health
                </DropdownMenuItem>
                {wizardUiEnabled && currentProjectId !== null && (
                    <PostHogErrorBoundary fallback={<></>}>
                        <Suspense fallback={null}>
                            <WizardRunsMoreMenuItem projectId={String(currentProjectId)} />
                        </Suspense>
                    </PostHogErrorBoundary>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={todayMenuLinkItem('https://posthog.com/changelog', { external: true })}
                    data-attr="more-menu-changelog-button"
                >
                    Changelog
                    <IconExternal data-icon="inline-end" className="ms-auto" />
                </DropdownMenuItem>
                <DropdownMenuItem render={todayMenuLinkItem(urls.exports())} data-attr="more-menu-exports-button">
                    Exports
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

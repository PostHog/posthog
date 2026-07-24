import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { finishedLocalRunLogic } from 'scenes/onboarding/shared/wizard-sync/finishedLocalRunLogic'
import { teamLogic } from 'scenes/teamLogic'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { ToolSetupModal } from '../shared/modals/ToolSetupModal'
import { QuickstartHeader } from '../shared/QuickstartHeader'
import { QuickstartPageShell } from '../shared/QuickstartPageShell'
import { QuickstartFocusedInstall } from './QuickstartFocusedInstall'
import { QuickstartSetupStatusChip } from './QuickstartSetupStatusChip'
import { SimplifiedToolsSections } from './SimplifiedToolsSections'

/** The test2 arm: a focused install view until the user moves on, then the tool cards. */
export function QuickstartSimplified(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    // A plain read, not detection: no polling, no live flips. The flag is only a lower bound
    // anyway (mobile SDKs often miss it), so leaving the install view is the user's call.
    const { hasIngestedEvent: installationComplete } = useValues(quickstartLogic)

    // Dismissal is the normal exit from the focused install view, persisted per project
    const dismissKey = `quickstart-install-dismissed-${currentTeamId ?? 'unknown'}`
    const [installDismissed, setInstallDismissed] = useState(() => localStorage.getItem(dismissKey) === 'true')
    const dismissFocusedInstall = (): void => {
        captureQuickstartAction('dismiss_focused_install')
        localStorage.setItem(dismissKey, 'true')
        setInstallDismissed(true)
    }
    const reopenFocusedInstall = (): void => {
        captureQuickstartAction('reopen_focused_install')
        localStorage.removeItem(dismissKey)
        setInstallDismissed(false)
    }

    // A completed wizard run finishes the install flow. Persist the exit without touching
    // state: the completed card (and its dashboard link) stays up for the current view, and
    // the next visit lands on the tool cards instead of an idle install panel.
    const { finishedLocalRun } = useValues(finishedLocalRunLogic)
    useEffect(() => {
        if (finishedLocalRun?.runPhase === 'completed' && localStorage.getItem(dismissKey) !== 'true') {
            captureQuickstartAction('install_flow_completed')
            localStorage.setItem(dismissKey, 'true')
        }
    }, [finishedLocalRun, dismissKey])
    // Pre-ingestion the page has one job (the first event), so the tool cards wait for data
    const focusedInstall = !installationComplete && !installDismissed

    return (
        <QuickstartPageShell>
            <QuickstartHeader
                installStatus={
                    !focusedInstall && (
                        <QuickstartSetupStatusChip
                            installationComplete={installationComplete}
                            installDismissed={installDismissed}
                            onReopen={reopenFocusedInstall}
                        />
                    )
                }
            />
            {focusedInstall ? (
                <QuickstartFocusedInstall onDismiss={dismissFocusedInstall} />
            ) : (
                <SimplifiedToolsSections />
            )}
            <ToolSetupModal installationComplete={installationComplete} />
        </QuickstartPageShell>
    )
}

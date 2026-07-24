import { useValues } from 'kea'
import { useState } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { QuickstartModals } from '../shared/modals/QuickstartModals'
import { QuickstartHeader } from '../shared/QuickstartHeader'
import { QuickstartPageShell } from '../shared/QuickstartPageShell'
import { QuickstartToolsSections } from '../shared/QuickstartToolsSections'
import { QuickstartFocusedInstall } from './QuickstartFocusedInstall'
import { QuickstartHeroAnswerCard } from './QuickstartHeroAnswerCard'
import { QuickstartSetupStatusChip } from './QuickstartSetupStatusChip'

/** The test2 arm: a focused install view until the user moves on, then a hero answer and the tool cards. */
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
                <>
                    <QuickstartHeroAnswerCard />
                    <QuickstartToolsSections />
                </>
            )}
            <QuickstartModals installationComplete={installationComplete} />
        </QuickstartPageShell>
    )
}

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCard, LemonSwitch, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ticketPatternAiScanLogic } from '../../components/TicketPatterns/ticketPatternAiScanLogic'

export function TicketPatternAiScanCard({ detectionEnabled }: { detectionEnabled: boolean }): JSX.Element {
    const { status, statusLoading, statusFailed, toggling } = useValues(ticketPatternAiScanLogic)
    const { enableScan, disableScan, loadStatus } = useActions(ticketPatternAiScanLogic)
    // The popover reads consent from this logic, so the switch has to read the same source, or
    // a consent granted a moment ago leaves the two disagreeing until the page reloads.
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const enabled = status?.enabled ?? false
    // Both endpoints need ticket editor. Creating a scout also needs skill editor, which the
    // server checks, so a person without it gets the toast rather than a dead switch.
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined
    const disabledReason = statusLoading
        ? 'Loading'
        : statusFailed
          ? "Couldn't load the scan status"
          : accessDisabledReason
            ? accessDisabledReason
            : !enabled && !detectionEnabled
              ? 'Turn on ticket pattern detection first'
              : undefined

    const onToggle = (next: boolean): void => {
        if (!next) {
            disableScan()
        } else if (dataProcessingAccepted) {
            enableScan()
        } else {
            setConsentRequested(true)
        }
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="font-medium">AI scan</label>
                    <p className="text-xs text-muted-alt mb-0">
                        Once an hour, a Signals scout reads the new tickets in this project and looks for an outage or a
                        bug that word matching misses. It reads the open patterns first, so it adds to them instead of
                        repeating them. Findings appear on the Patterns tab and in the Inbox. Ticket text is sent to an
                        AI model, and each run uses AI credits.
                    </p>
                </div>
                <AIConsentPopoverWrapper
                    placement="top"
                    showArrow
                    ignoreDismissal
                    hideTrainingDisclaimer
                    hidden={!consentRequested}
                    onApprove={() => {
                        setConsentRequested(false)
                        enableScan()
                    }}
                    onDismiss={() => setConsentRequested(false)}
                >
                    <LemonSwitch
                        checked={enabled}
                        onChange={onToggle}
                        loading={statusLoading || toggling}
                        disabledReason={disabledReason}
                        aria-label="AI scan"
                        data-attr="ticket-pattern-ai-scan-toggle"
                    />
                </AIConsentPopoverWrapper>
            </div>
            {statusFailed ? (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-alt">
                    <span>Couldn't load the scan status.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadStatus()}>
                        Try again
                    </LemonButton>
                </div>
            ) : null}
            {enabled && !detectionEnabled ? (
                <p className="text-xs text-warning mb-0">
                    Ticket pattern detection is off, but the AI scan still runs every hour and uses AI credits. Turn the
                    scan off here if you do not want that.
                </p>
            ) : null}
            {status?.skill_name ? (
                <p className="text-xs text-muted-alt mb-0">
                    {/* Each branch keeps its own element, so a switch removes an element rather than a
                        text node that a page-translation extension may have replaced. */}
                    {status.last_run_at ? (
                        <span>
                            Last run <TZLabel time={status.last_run_at} />.{' '}
                        </span>
                    ) : enabled ? (
                        <span>The first run starts within the hour. </span>
                    ) : null}
                    <Link to={urls.inboxScout(status.skill_name)}>Open the scout in the Inbox</Link> to read its notes
                    or change how it works.
                </p>
            ) : null}
        </LemonCard>
    )
}

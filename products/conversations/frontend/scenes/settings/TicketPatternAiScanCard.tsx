import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonCard, LemonSwitch, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { ticketPatternAiScanLogic } from '../../components/TicketPatterns/ticketPatternAiScanLogic'

export function TicketPatternAiScanCard(): JSX.Element {
    const { status, statusLoading, toggling } = useValues(ticketPatternAiScanLogic)
    const { enableScan, disableScan } = useActions(ticketPatternAiScanLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const enabled = status?.enabled ?? false
    const consentGranted = status?.ai_consent_granted ?? false

    const onToggle = (next: boolean): void => {
        if (!next) {
            disableScan()
        } else if (consentGranted) {
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
                        disabledReason={statusLoading ? 'Loading' : undefined}
                        data-attr="ticket-pattern-ai-scan-toggle"
                    />
                </AIConsentPopoverWrapper>
            </div>
            {status?.skill_name ? (
                <p className="text-xs text-muted-alt mb-0">
                    {status.last_run_at ? (
                        <>
                            Last run <TZLabel time={status.last_run_at} />.{' '}
                        </>
                    ) : enabled ? (
                        'The first run starts within the hour. '
                    ) : null}
                    <Link to={urls.inboxScout(status.skill_name)}>Open the scout in the Inbox</Link> to read its notes
                    or change how it works.
                </p>
            ) : null}
        </LemonCard>
    )
}

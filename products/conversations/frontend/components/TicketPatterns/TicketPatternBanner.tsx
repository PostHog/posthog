import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { ticketPatternsLogic } from './ticketPatternsLogic'

function patternSummary(pattern: TicketPatternApi): string {
    const tickets = pattern.ticket_count === 1 ? '1 ticket' : `${pattern.ticket_count} tickets`
    const customers = pattern.requester_count === 1 ? '1 customer' : `${pattern.requester_count} customers`
    return `${tickets} from ${customers} about "${pattern.topic}"`
}

export function TicketPatternBanner(): JSX.Element | null {
    const { patternsEnabled, bannerPatterns, inFlightIds } = useValues(ticketPatternsLogic)
    const { confirmPattern, dismissPattern, hideBanner, loadOpenPatterns } = useActions(ticketPatternsLogic)

    useEffect(() => {
        if (patternsEnabled) {
            loadOpenPatterns()
        }
    }, [patternsEnabled, loadOpenPatterns])

    if (!patternsEnabled || bannerPatterns.length === 0) {
        return null
    }

    // Both transitions need editor access on tickets, while reading a pattern only needs viewer.
    const decisionDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    return (
        <div className="flex flex-col gap-2">
            {bannerPatterns.map((pattern) => {
                const busy = inFlightIds.includes(pattern.id)
                return (
                    <LemonBanner
                        key={pattern.id}
                        type="warning"
                        onClose={() => hideBanner(pattern.id)}
                        action={{
                            children: 'Review',
                            to: urls.supportPatterns(),
                            'data-attr': 'ticket-pattern-banner-review',
                        }}
                    >
                        <div className="flex flex-col gap-1">
                            <div>
                                <strong>Possible emerging issue.</strong>{' '}
                                <span translate="no">{patternSummary(pattern)}</span>
                                {pattern.first_ticket_at ? (
                                    <>
                                        <span> since </span>
                                        <TZLabel time={pattern.first_ticket_at} />
                                    </>
                                ) : null}
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <LemonButton
                                    size="xsmall"
                                    type="primary"
                                    loading={busy}
                                    disabledReason={busy ? 'Saving' : decisionDisabledReason}
                                    onClick={() => confirmPattern(pattern.id)}
                                    data-attr="ticket-pattern-banner-confirm"
                                >
                                    Confirm
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    loading={busy}
                                    disabledReason={busy ? 'Saving' : decisionDisabledReason}
                                    onClick={() => dismissPattern(pattern.id)}
                                    data-attr="ticket-pattern-banner-dismiss"
                                >
                                    Not an issue
                                </LemonButton>
                            </div>
                        </div>
                    </LemonBanner>
                )
            })}
        </div>
    )
}

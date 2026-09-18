import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { spikeKey, ticketSpikeBannerLogic } from './ticketSpikeBannerLogic'

// The list narrows to exactly these tickets. The topic stays out of the URL for the same reason
// the search box does: a model wrote it from customer messages, and query strings reach browser
// history, copied links and request logs.
function spikeTicketsUrl(spike: TicketPatternApi): string {
    return combineUrl(urls.supportTickets(), { ids: spike.ticket_ids.join(',') }).url
}

function SpikeBanner({ spike }: { spike: TicketPatternApi }): JSX.Element {
    const { dismissSpike } = useActions(ticketSpikeBannerLogic)

    return (
        <LemonBanner type="warning" onClose={() => dismissSpike(spikeKey(spike))} data-attr="ticket-spike-banner">
            <Link to={spikeTicketsUrl(spike)} className="font-semibold" data-attr="ticket-spike-banner-tickets">
                {spike.topic}
            </Link>
            <span>
                {' '}
                reported by {spike.requester_count} customers across {spike.ticket_count} tickets,{' '}
                {humanFriendlyDetailedTime(spike.detected_at)}.
            </span>
            {spike.summary ? <p className="mb-0 mt-1">{spike.summary}</p> : null}
        </LemonBanner>
    )
}

export function TicketSpikeBanner(): JSX.Element | null {
    const { visibleSpikes, dismissedSpikes, expanded } = useValues(ticketSpikeBannerLogic)
    const { setExpanded } = useActions(ticketSpikeBannerLogic)

    if (!visibleSpikes.length && !dismissedSpikes.length) {
        return null
    }

    // Only the newest spike gets a banner. Several at once would push the ticket list off screen,
    // and the list is what the team came here for.
    const [newest, ...rest] = visibleSpikes
    const hiddenCount = rest.length + dismissedSpikes.length

    return (
        <div className="flex flex-col gap-2">
            {newest ? <SpikeBanner spike={newest} /> : null}
            {hiddenCount > 0 && !expanded && (
                <Link
                    subtle
                    onClick={() => setExpanded(true)}
                    className="text-xs text-muted-alt"
                    data-attr="ticket-spike-banner-expand"
                >
                    {hiddenCount} more {hiddenCount === 1 ? 'spike' : 'spikes'} from the last day
                </Link>
            )}
            {expanded && (
                <>
                    {rest.map((spike) => (
                        <SpikeBanner key={spikeKey(spike)} spike={spike} />
                    ))}
                    {/* Dismissed spikes stay listed, muted, so a teammate can see one was picked up
                        and by whom rather than finding an empty inbox. */}
                    {dismissedSpikes.map((spike) => (
                        <p key={spikeKey(spike)} className="text-xs text-muted-alt mb-0">
                            <Link subtle to={spikeTicketsUrl(spike)} data-attr="ticket-spike-dismissed-tickets">
                                {spike.topic}
                            </Link>
                            {spike.dismissed_by ? ` - dismissed by ${spike.dismissed_by}` : ' - dismissed'}
                        </p>
                    ))}
                    <Link
                        subtle
                        onClick={() => setExpanded(false)}
                        className="text-xs text-muted-alt"
                        data-attr="ticket-spike-banner-collapse"
                    >
                        Show less
                    </Link>
                </>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { spikeKey, ticketSpikeBannerLogic } from './ticketSpikeBannerLogic'

export function TicketSpikeBanner(): JSX.Element | null {
    const { visibleSpikes } = useValues(ticketSpikeBannerLogic)
    const { dismissSpike } = useActions(ticketSpikeBannerLogic)

    if (!visibleSpikes.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {visibleSpikes.map((spike: TicketPatternApi) => (
                <LemonBanner
                    key={spikeKey(spike)}
                    type="warning"
                    onClose={() => dismissSpike(spikeKey(spike))}
                    data-attr="ticket-spike-banner"
                >
                    <span className="font-semibold">{spike.topic}</span>
                    <span>
                        {' '}
                        reported by {spike.requester_count} customers across {spike.ticket_count} tickets,{' '}
                        {humanFriendlyDetailedTime(spike.detected_at)}.
                    </span>
                    {spike.summary ? <p className="mb-0 mt-1">{spike.summary}</p> : null}
                </LemonBanner>
            ))}
        </div>
    )
}

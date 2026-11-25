import { TZLabel } from 'lib/components/TZLabel'

import { PartnerReviewEventApi } from '~/generated/core/api.schemas'

import { reviewEventTitle } from '../oauthAppProvisioningStatus'

export function OAuthAppReviewTimeline({ events }: { events: readonly PartnerReviewEventApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="font-semibold">History</span>
            <ol className="m-0 p-0 list-none flex flex-col gap-3 border-l border-primary pl-3">
                {events.map((event, index) => (
                    <li key={`${event.at}-${index}`} className="flex flex-col gap-0.5">
                        <span className="text-xs text-secondary">
                            <TZLabel time={event.at} />
                        </span>
                        <span className="font-medium">{reviewEventTitle(event)}</span>
                        {event.message && (
                            <p className="m-0 whitespace-pre-wrap border rounded p-2 bg-surface-secondary">
                                {event.message}
                            </p>
                        )}
                    </li>
                ))}
            </ol>
        </div>
    )
}

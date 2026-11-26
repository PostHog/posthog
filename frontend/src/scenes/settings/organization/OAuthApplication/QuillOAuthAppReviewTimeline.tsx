import { Item, ItemContent, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { PartnerReviewEventApi } from '~/generated/core/api.schemas'

import { reviewEventTitle } from '../oauthAppProvisioningStatus'

export function QuillOAuthAppReviewTimeline({ events }: { events: readonly PartnerReviewEventApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" weight="semibold" render={<span />}>
                History
            </Text>
            <ol className="m-0 p-0 list-none flex flex-col gap-3 border-l border-border pl-3">
                {events.map((event, index) => (
                    <li key={`${event.at}-${index}`} className="flex flex-col gap-0.5">
                        <Text size="xs" variant="muted" render={<span />}>
                            <TZLabel time={event.at} />
                        </Text>
                        <Text size="xs" weight="medium" render={<span />}>
                            {reviewEventTitle(event)}
                        </Text>
                        {event.message && (
                            <Item variant="muted" size="sm">
                                <ItemContent>
                                    <Text size="xs" render={<p className="m-0 whitespace-pre-wrap" />}>
                                        {event.message}
                                    </Text>
                                </ItemContent>
                            </Item>
                        )}
                    </li>
                ))}
            </ol>
        </div>
    )
}

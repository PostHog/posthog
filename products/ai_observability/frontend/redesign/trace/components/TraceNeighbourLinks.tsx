import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface TraceNeighbourLinksProps {
    olderHref: string | null
    newerHref: string | null
}

export function TraceNeighbourLinks({ olderHref, newerHref }: TraceNeighbourLinksProps): JSX.Element {
    return (
        <div className="flex gap-1">
            <LemonButton
                size="small"
                icon={<IconChevronDown className="rotate-180" />}
                to={newerHref ?? undefined}
                disabledReason={newerHref ? undefined : 'No newer trace'}
                tooltip="Newer trace"
                aria-label="Newer trace"
                data-attr="trace-view-newer-trace"
            />
            <LemonButton
                size="small"
                icon={<IconChevronDown />}
                to={olderHref ?? undefined}
                disabledReason={olderHref ? undefined : 'No older trace'}
                tooltip="Older trace"
                aria-label="Older trace"
                data-attr="trace-view-older-trace"
            />
        </div>
    )
}

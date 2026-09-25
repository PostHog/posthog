import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TraceNeighbourLinks } from './TraceNeighbourLinks'
import { TraceStatusBadge } from './TraceStatusBadge'

export interface TraceHeaderProps {
    name: string
    hasError: boolean
    olderHref: string | null
    newerHref: string | null
    backHref: string
}

export function TraceHeader({ name, hasError, olderHref, newerHref, backHref }: TraceHeaderProps): JSX.Element {
    return (
        <header className="flex flex-wrap items-center gap-2">
            <LemonButton
                size="small"
                icon={<IconArrowLeft />}
                to={backHref}
                tooltip="Back to traces"
                aria-label="Back to traces"
                data-attr="trace-view-back"
            />
            <h1 className="m-0 min-w-0 truncate text-lg font-semibold">{name}</h1>
            <TraceStatusBadge hasError={hasError} />
            <div className="ml-auto">
                <TraceNeighbourLinks olderHref={olderHref} newerHref={newerHref} />
            </div>
        </header>
    )
}

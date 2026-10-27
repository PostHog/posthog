import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'
import { TraceExportButton, TraceExportButtonProps } from './TraceExportButton'
import { TraceNeighbourLinks } from './TraceNeighbourLinks'
import { TraceStatusBadge } from './TraceStatusBadge'

export interface TraceHeaderProps {
    name: string
    hasError: boolean
    olderHref: string | null
    newerHref: string | null
    backLink: LabeledLink
    exportAction?: TraceExportButtonProps
}

export function TraceHeader({
    name,
    hasError,
    olderHref,
    newerHref,
    backLink,
    exportAction,
}: TraceHeaderProps): JSX.Element {
    return (
        <header className="flex flex-wrap items-center gap-2">
            <LemonButton
                size="small"
                icon={<IconArrowLeft />}
                to={backLink.href}
                tooltip={backLink.label}
                aria-label={backLink.label}
                data-attr="trace-view-back"
            />
            <h1 className="m-0 min-w-0 truncate text-lg font-semibold">{name}</h1>
            <TraceStatusBadge hasError={hasError} />
            <div className="ml-auto flex items-center gap-2">
                {exportAction ? <TraceExportButton {...exportAction} /> : null}
                <TraceNeighbourLinks olderHref={olderHref} newerHref={newerHref} />
            </div>
        </header>
    )
}

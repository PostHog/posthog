import { Text } from '@posthog/quill'

import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { waitingText } from './pipelineHealthStats'

/** The warehouse stage of one source or table: its landing state, when it last landed, how long it has waited and why it failed. */
export function WarehouseLandingCell({
    landingState,
    appliedAt,
    pendingSince,
    error,
}: {
    landingState: string
    appliedAt: string | null
    pendingSince: string | null
    error?: string | null
}): JSX.Element {
    const waiting = waitingText(pendingSince)
    return (
        <div className="flex items-center gap-2 whitespace-nowrap">
            <WarehouseStatusBadge status={landingState} />
            {appliedAt ? (
                <Text size="xs" variant="muted" render={<span />}>
                    Landed <WarehouseTime iso={appliedAt} />
                </Text>
            ) : null}
            {waiting ? (
                <Text size="xs" className="tabular-nums text-[var(--warning-foreground)]" render={<span />}>
                    {waiting}
                </Text>
            ) : null}
            {error ? (
                <Text
                    size="xs"
                    variant="destructive"
                    className="block max-w-48 truncate"
                    title={error}
                    render={<span />}
                >
                    {error}
                </Text>
            ) : null}
        </div>
    )
}

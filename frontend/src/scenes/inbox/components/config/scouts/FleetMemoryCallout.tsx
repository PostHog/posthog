import { useValues } from 'kea'

import { IconArrowRight, IconNotebook } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { scratchpadLogic } from '../../../logics/scratchpadLogic'

/**
 * "Fleet memory" stat card for the scout troop list. Surfaces that the fleet keeps durable memory
 * about this project — count + recency carry the "scouts learn over time" story — and links into the
 * full scratchpad browse/search surface. Renders nothing until there is at least one memory, so a
 * fresh project isn't nudged toward an empty page.
 */
export function FleetMemoryCallout({ onOpen }: { onOpen: () => void }): JSX.Element | null {
    const { entries, totalCount, lastUpdatedAt, latestKey } = useValues(scratchpadLogic)

    // Hold until the first load settles, then only show when there's something to read.
    if (entries === null || !totalCount) {
        return null
    }

    return (
        <button
            type="button"
            onClick={onOpen}
            className="flex w-full items-center gap-3 rounded border border-primary bg-bg-light px-4 py-3.5 text-left transition-colors hover:border-primary-3000 hover:bg-bg-3000"
        >
            <IconNotebook className="size-5 shrink-0 text-primary-3000" />
            <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-default">Fleet memory</span>
                <span className="truncate text-xs text-secondary leading-snug">
                    Your scouts have recorded {pluralize(totalCount, 'thing')} they've learned about this project
                    {lastUpdatedAt ? (
                        <>
                            {' · updated '}
                            <TZLabel time={lastUpdatedAt} />
                        </>
                    ) : null}
                    {latestKey ? <span className="text-muted"> · latest “{latestKey}”</span> : null}
                </span>
            </div>
            <span className="flex-1" />
            <IconArrowRight className="size-4 shrink-0 text-muted" />
        </button>
    )
}

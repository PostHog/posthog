import { useValues } from 'kea'

import { IconArrowRight, IconSparkles } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'

/**
 * Findings stat card for the scout troop list, above the scratchpad callout. Advertises the troop's
 * recent findings (count · scouts · recency) and links into the cross-fleet findings page. Reads the
 * cheap `emittedFindingsSummary` (a single backend query) so it appears as soon as that lands rather
 * than after the full paginated runs-window walk. Renders nothing until there's at least one finding.
 */
export function FleetFindingsCallout({ onOpen }: { onOpen: () => void }): JSX.Element | null {
    const { emittedFindingsSummary, fleetFindingsSummaryLoadedOnce } = useValues(scoutFleetLogic)

    // Hold until the cheap summary lands, then only show when there's something to read.
    if (!fleetFindingsSummaryLoadedOnce || emittedFindingsSummary.count === 0) {
        return null
    }

    return (
        <button
            type="button"
            onClick={onOpen}
            className="flex w-full items-center gap-3 rounded border border-primary bg-bg-light px-4 py-3.5 text-left transition-colors hover:border-primary-3000 hover:bg-bg-3000"
        >
            <IconSparkles className="size-5 shrink-0 text-primary-3000" />
            <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-default">Scout findings</span>
                <span className="truncate text-xs text-secondary leading-snug">
                    {pluralize(emittedFindingsSummary.count, 'finding')} across{' '}
                    {pluralize(emittedFindingsSummary.scoutCount, 'scout')}
                    {emittedFindingsSummary.latestAt ? (
                        <>
                            {' · latest '}
                            <TZLabel time={emittedFindingsSummary.latestAt} />
                        </>
                    ) : null}
                </span>
            </div>
            <span className="flex-1" />
            <IconArrowRight className="size-4 shrink-0 text-muted" />
        </button>
    )
}

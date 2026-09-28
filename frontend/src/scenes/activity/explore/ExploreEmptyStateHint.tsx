import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { eventsSceneLogic } from './eventsSceneLogic'

const FALLBACK_DETAIL = 'Try changing the date range, or pick another action, event or breakdown.'

/**
 * Rendered in place of the generic "no matching events" copy. The explore view defaults to the last
 * hour and applies the team's test account filter, so an event that is ingested and queryable can
 * still be missing here with nothing on screen to say why.
 */
export function ExploreEmptyStateHint(): JSX.Element {
    const { hiddenEventsProbe } = useValues(eventsSceneLogic())
    const { probeForHiddenEvents, widenToHiddenEvents, dropTestAccountFilter } = useActions(eventsSceneLogic())

    useOnMountEffect(() => {
        probeForHiddenEvents()
    })

    if (!hiddenEventsProbe) {
        return (
            <span className="flex items-center justify-center gap-2">
                <Spinner />
                Checking for events outside this time range
            </span>
        )
    }

    if (hiddenEventsProbe.latestOutsideWindow) {
        return (
            <span className="flex flex-wrap items-center justify-center gap-x-1 gap-y-2">
                <span>
                    Matching events exist outside this time range. The most recent one is from{' '}
                    <TZLabel time={hiddenEventsProbe.latestOutsideWindow} />.
                </span>
                <LemonButton type="secondary" size="xsmall" onClick={widenToHiddenEvents}>
                    Show that time range
                </LemonButton>
            </span>
        )
    }

    if (hiddenEventsProbe.hiddenByTestAccountFilter) {
        return (
            <span className="flex flex-wrap items-center justify-center gap-x-1 gap-y-2">
                <span>Matching events exist, but the test account filter hides them.</span>
                <LemonButton type="secondary" size="xsmall" onClick={dropTestAccountFilter}>
                    Turn the filter off
                </LemonButton>
            </span>
        )
    }

    return <>{FALLBACK_DETAIL}</>
}

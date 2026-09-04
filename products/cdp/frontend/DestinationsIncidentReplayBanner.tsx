import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { isRerunnableHogFunctionType } from 'scenes/hog-functions/invocations/hogInvocationsLogic'
import { urls } from 'scenes/urls'

import { type AffectedDestination, destinationsIncidentReplayLogic } from './destinationsIncidentReplayLogic'

// Mirrors the server-side HOG_INVOCATION_RERUN_MAX_COUNT default: one replay request queues at
// most this many invocations, so a busier destination needs a second pass.
const RERUN_MAX_COUNT_PER_REQUEST = 10000

function replayBlockedReason(destination: AffectedDestination): string | undefined {
    if (!destination.enabled) {
        return 'This destination is disabled. Enable it to replay its failed events.'
    }
    if (!isRerunnableHogFunctionType(destination.type)) {
        return 'This type of destination cannot be replayed.'
    }
    if (destination.failedCount === 0) {
        return 'There is nothing left to replay.'
    }
    return undefined
}

/**
 * A replay sends real events to the third party, so it gets the same confirmation the per-invocation
 * and bulk rerun buttons already use. It matters more here: one click covers the whole backlog.
 */
function confirmReplay(destination: AffectedDestination, replayDestination: (id: string) => void): void {
    LemonDialog.open({
        title: `Replay failed events for ${destination.name || 'this destination'}?`,
        content: `This sends ${humanFriendlyNumber(destination.failedCount)} failed ${
            destination.failedCount === 1 ? 'event' : 'events'
        } to the destination again, starting from August 18. Events the destination already processed are sent a second time.`,
        primaryButton: {
            children: 'Replay',
            onClick: () => replayDestination(destination.id),
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function DestinationsIncidentReplayBanner(): JSX.Element | null {
    const { showBanner, affectedDestinations, replayStatusById, currentProjectId } = useValues(
        destinationsIncidentReplayLogic
    )
    const { replayDestination } = useActions(destinationsIncidentReplayLogic)

    if (!showBanner) {
        return null
    }

    const hasLargeBacklog = affectedDestinations.some(
        (destination) => destination.failedCount > RERUN_MAX_COUNT_PER_REQUEST
    )

    return (
        <LemonBanner
            type="warning"
            // Per project: without the suffix, dismissing in one project hides the recovery path
            // in every other project this browser visits.
            dismissKey={`destinations-incident-replay-2026-08-18-${currentProjectId}`}
        >
            {/* LemonBanner takes no data-attr, so the hook for autocapture and tests sits here. */}
            <div className="flex flex-col gap-2" data-attr="destinations-incident-replay-banner">
                <div>
                    On August 18 an incident on our side replaced the saved credentials on some destinations with a
                    placeholder, so their events stopped being delivered. We can't recover the original values. Any
                    destination below marked "Enter credentials" is affected, and needs its credentials again. The rest
                    have events that failed since August 18, which may or may not be related, and you can replay those.
                    {hasLargeBacklog ? (
                        <> A replay covers up to 10,000 failed events per run. Replay again to send the rest.</>
                    ) : null}
                </div>
                <ul className="flex flex-col gap-1">
                    {affectedDestinations.map((destination) => {
                        const status = replayStatusById[destination.id]
                        const blockedReason = replayBlockedReason(destination)
                        return (
                            <li key={destination.id} className="flex items-center gap-2">
                                {destination.needsCredentials ? (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        data-attr="destinations-incident-credentials-button"
                                        to={urls.hogFunction(destination.id, 'configuration')}
                                    >
                                        Enter credentials
                                    </LemonButton>
                                ) : (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        data-attr="destinations-incident-replay-button"
                                        loading={status === 'pending'}
                                        disabledReason={
                                            status === 'queued'
                                                ? 'Replay queued. Refresh the page to replay again once it finishes.'
                                                : blockedReason
                                        }
                                        onClick={() => confirmReplay(destination, replayDestination)}
                                    >
                                        {status === 'queued' ? 'Replay queued' : 'Replay failed events'}
                                    </LemonButton>
                                )}
                                <LemonButton size="xsmall" to={urls.hogFunction(destination.id, 'configuration')}>
                                    {destination.name}
                                </LemonButton>
                                {destination.failedCount > 0 ? (
                                    <span className="text-secondary">
                                        {humanFriendlyNumber(destination.failedCount)} failed{' '}
                                        {destination.failedCount === 1 ? 'event' : 'events'}
                                    </span>
                                ) : null}
                            </li>
                        )
                    })}
                </ul>
            </div>
        </LemonBanner>
    )
}

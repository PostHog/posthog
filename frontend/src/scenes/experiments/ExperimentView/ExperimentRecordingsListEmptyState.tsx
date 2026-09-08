import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import {
    ExperimentRecordingsEmptyAction,
    ExperimentRecordingsListEmptyContext,
    ExperimentReplayListEmptyReason,
    experimentReplayTabLogic,
} from './experimentReplayTabLogic'

// The two hints the shared replay panel offers, kept at the same URLs so a viewer who knows one
// surface lands on the same page from the other.
const RETENTION_DOCS = 'https://posthog.com/docs/session-replay/data-retention'
const AD_BLOCKER_DOCS = 'https://posthog.com/docs/session-replay/troubleshooting#4-adtracking-blockers'

/** How long ago the run started, as the copy says it. Day zero has no count that reads right. */
function startedWhen(daysSinceStart: number | null): string {
    if (daysSinceStart === null || daysSinceStart <= 0) {
        return 'today'
    }
    return `${pluralize(daysSinceStart, 'day')} ago`
}

/**
 * One banner per reason, each naming what happened and what to do about it. Modeled on the
 * behavior-comparison shelf's empty states.
 */
function ReasonBanner({
    reason,
    context,
    onAction,
}: {
    reason: ExperimentReplayListEmptyReason
    context: ExperimentRecordingsListEmptyContext
    onAction: (action: ExperimentRecordingsEmptyAction) => void
}): JSX.Element {
    if (reason === ExperimentReplayListEmptyReason.ReplayDisabled) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Replay settings',
                    to: urls.settings('environment-replay'),
                    onClick: () => onAction('replay_settings'),
                    'data-attr': 'experiment-recordings-empty-replay-settings',
                }}
            >
                Session replay is off for this project, so none of the sessions in this experiment were recorded. Turn
                it on to record new sessions.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.NotLaunched) {
        return <LemonBanner type="info">Launch the experiment to see recordings of participants.</LemonBanner>
    }
    if (reason === ExperimentReplayListEmptyReason.TooEarly) {
        return (
            <LemonBanner type="info">
                No recordings yet. The experiment started {startedWhen(context.daysSinceStart)}, and a recording appears
                here once an exposed person's session has been captured.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.EndedPastRetention) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'How retention works',
                    to: RETENTION_DOCS,
                    targetBlank: true,
                    onClick: () => onAction('retention_docs'),
                    'data-attr': 'experiment-recordings-empty-retention-docs',
                }}
            >
                This experiment ended on {dayjs(context.endDate).format('MMM D, YYYY')}. This project keeps recordings
                for {pluralize(context.retentionWindowDays, 'day')}, so the recordings from its run are no longer
                stored.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.MetricFilterMatchedNothing) {
        return (
            <LemonBanner type="info">
                No recordings matched the metric filter. Change or clear the filter above to widen the list.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.MetricFilterFailed) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Try again',
                    onClick: () => onAction('retry_metric_filter'),
                    'data-attr': 'experiment-recordings-empty-retry-metric-filter',
                }}
            >
                The metric filter could not be loaded, so the list has nothing to show.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.FiltersNarrowed) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Clear filters',
                    onClick: () => onAction('clear_filters'),
                    'data-attr': 'experiment-recordings-empty-clear-filters',
                }}
            >
                No recordings match the filters added above. Clear them to widen the list back to everyone exposed.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.VariantHasNone) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Show all variants',
                    onClick: () => onAction('show_all_variants'),
                    'data-attr': 'experiment-recordings-empty-show-all-variants',
                }}
            >
                No recordings for the {context.variantKey} variant. The other variants can still have some.
            </LemonBanner>
        )
    }
    if (reason === ExperimentReplayListEmptyReason.InSessionHasNone) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'All sessions',
                    onClick: () => onAction('all_sessions'),
                    'data-attr': 'experiment-recordings-empty-all-sessions',
                }}
            >
                No recordings of the sessions the exposure happened in. The same people can still have recordings of
                their other sessions.
            </LemonBanner>
        )
    }
    return (
        <LemonBanner type="info">
            <div className="flex flex-col gap-1">
                <span>
                    No recordings found for the people exposed to this experiment. A session can be missing for a few
                    reasons:
                </span>
                <Link
                    to={RETENTION_DOCS}
                    target="_blank"
                    data-attr="experiment-recordings-empty-retention-docs"
                    onClick={() => onAction('retention_docs')}
                >
                    Recordings might be outside the retention period
                </Link>
                <Link
                    to={AD_BLOCKER_DOCS}
                    target="_blank"
                    data-attr="experiment-recordings-empty-ad-blocker-docs"
                    onClick={() => onAction('ad_blocker_docs')}
                >
                    An ad blocker might be preventing recordings
                </Link>
            </div>
        </LemonBanner>
    )
}

/**
 * Why this experiment's recordings list came back empty. Replaces the shared replay troubleshooting
 * panel on the tab, which can only offer the generic hints and whose "Search over the last 30 days"
 * button would overwrite the experiment's own run window.
 */
export function ExperimentRecordingsListEmptyState({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentReplayTabLogic({ experiment })
    const { listEmptyReason, listEmptyContext, recordingsFilters, sessionBucketLoading } = useValues(logic)
    const { listEmptyActionClicked, loadSessionBucket, setSelectedVariantKey, setExposureScope } = useActions(logic)
    const { hiddenRecordingsCount } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)

    const recordingsAreHidden = hideViewedRecordings !== false

    const runAction = (action: ExperimentRecordingsEmptyAction): void => {
        listEmptyActionClicked(action)
        if (action === 'retry_metric_filter') {
            loadSessionBucket()
        } else if (action === 'show_all_variants') {
            setSelectedVariantKey(null)
        } else if (action === 'all_sessions') {
            setExposureScope('all_exposed')
        } else if (action === 'clear_filters') {
            // The playlist's own reset would drop the tab's scoping too, so the tab's filters go
            // back in whole rather than the playlist defaults.
            setFilters(recordingsFilters)
        }
    }

    return (
        <div className="flex flex-col gap-2" data-attr="experiment-recordings-empty-state">
            {recordingsAreHidden && (
                <LemonButton
                    type="secondary"
                    fullWidth={true}
                    size="xsmall"
                    data-attr="experiment-recordings-empty-show-hidden"
                    onClick={() => {
                        listEmptyActionClicked('show_hidden')
                        setShowSettings(true)
                        setHideViewedRecordings(false)
                    }}
                >
                    {hiddenRecordingsCount > 0
                        ? `Show ${pluralize(hiddenRecordingsCount, 'hidden recording')}`
                        : 'Show hidden recordings'}
                </LemonButton>
            )}
            {/* The client-side backstop hid rows the server let through, so the list is empty only
                because of the setting. A reason names a cause of emptiness, and there is none here.
                An in-flight bucket has the same shape as one that matched nothing, so a reason there
                would claim an answer the request has not given yet. The caption above the playlist
                carries the wait. */}
            {hiddenRecordingsCount === 0 && !sessionBucketLoading && (
                <ReasonBanner reason={listEmptyReason} context={listEmptyContext} onAction={runAction} />
            )}
        </div>
    )
}

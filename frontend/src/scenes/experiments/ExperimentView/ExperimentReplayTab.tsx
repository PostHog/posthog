import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'

import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

import { Experiment } from '~/types'

import { isLaunched } from '../experimentStatus'
import { EXPOSURE_UNLINKABLE_REASON, METRIC_UNLINKABLE_REASON } from '../viewRecordingsLinkabilityLogic'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'

// LemonSegmentedButton values must be strings; the logic stores null for "All". Variant keys are
// restricted to [a-zA-Z0-9_-], so the '$' prefix guarantees no collision with a real variant — a
// variant literally named "all" just renders as its own option after the built-in "All".
const ALL_VARIANTS = '$all'
// Metric facet counterpart: metric uuids never start with '$'.
const NO_METRIC = '$none'

export function ExperimentReplayTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentReplayTabLogic({ experiment })
    const {
        effectiveVariantKey,
        variantKeys,
        recordingsFilters,
        exposureUnlinkable,
        effectiveMetricUuid,
        metricOptions,
    } = useValues(logic)
    const { setSelectedVariantKey, setSelectedMetricUuid } = useActions(logic)

    if (!isLaunched(experiment)) {
        return <LemonBanner type="info">Launch the experiment to see recordings of participants.</LemonBanner>
    }

    if (exposureUnlinkable) {
        return <LemonBanner type="warning">{EXPOSURE_UNLINKABLE_REASON}</LemonBanner>
    }

    return (
        <div data-attr="experiment-recordings-tab">
            <div className="mb-2 flex flex-wrap gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={effectiveVariantKey ?? ALL_VARIANTS}
                    onChange={(value) => setSelectedVariantKey(value === ALL_VARIANTS ? null : value)}
                    options={[
                        { value: ALL_VARIANTS, label: 'All' },
                        ...variantKeys.map((key) => ({ value: key, label: key })),
                    ]}
                />
                {metricOptions.length > 0 && (
                    <div data-attr="experiment-recordings-metric-filter">
                        <LemonSegmentedButton
                            size="small"
                            value={effectiveMetricUuid ?? NO_METRIC}
                            onChange={(value) => setSelectedMetricUuid(value === NO_METRIC ? null : value)}
                            options={[
                                {
                                    value: NO_METRIC,
                                    label: 'Any activity',
                                    tooltip: "Don't filter by metric events",
                                },
                                ...metricOptions.map((option) => ({
                                    value: option.uuid,
                                    label: `Reached ${option.name}`,
                                    disabledReason: option.unlinkable ? METRIC_UNLINKABLE_REASON : undefined,
                                })),
                            ]}
                        />
                    </div>
                )}
            </div>
            <div className="SessionRecordingPlaylistHeightWrapper">
                <SessionRecordingsPlaylist
                    logicKey={`experiment-${experiment.id}`}
                    filters={recordingsFilters}
                    updateSearchParams={false}
                />
            </div>
        </div>
    )
}

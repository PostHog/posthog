import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

import { Experiment } from '~/types'

import { isLaunched } from '../experimentStatus'
import { EXPOSURE_UNLINKABLE_REASON, METRIC_UNLINKABLE_REASON } from '../viewRecordingsLinkabilityLogic'
import { experimentReplayTabLogic } from './experimentReplayTabLogic'
import { VariantTag } from './VariantTag'

// LemonSegmentedButton values must be strings; the logic stores null for "All". Variant keys are
// restricted to [a-zA-Z0-9_-], so the '$' prefix guarantees no collision with a real variant — a
// variant literally named "all" just renders as its own option after the built-in "All".
const ALL_VARIANTS = '$all'

export function ExperimentReplayTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentReplayTabLogic({ experiment })
    const {
        effectiveVariantKey,
        variantKeys,
        recordingsFilters,
        exposureUnlinkable,
        effectiveMetricUuids,
        metricOptions,
    } = useValues(logic)
    const { setSelectedVariantKey, setMetricSelected } = useActions(logic)

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
                        ...variantKeys.map((key) => ({ value: key, label: <VariantTag variantKey={key} /> })),
                    ]}
                />
                {metricOptions.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    sideIcon={<IconChevronDown />}
                                    tooltip="Only show sessions that fired events for every selected metric. Whether a session fired a metric's events can differ from what the experiment analysis counts."
                                    data-attr="experiment-recordings-metric-filter"
                                />
                            }
                        >
                            {effectiveMetricUuids.length > 0
                                ? `Metric events (${effectiveMetricUuids.length})`
                                : 'Metric events'}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-fit max-w-100">
                            {metricOptions.map((option) => (
                                <DropdownMenuCheckboxItem
                                    key={option.uuid}
                                    checked={effectiveMetricUuids.includes(option.uuid)}
                                    onCheckedChange={(checked: boolean) => setMetricSelected(option.uuid, checked)}
                                    closeOnClick={false}
                                    disabled={option.unlinkable}
                                    data-attr="experiment-recordings-metric-option"
                                >
                                    {option.unlinkable ? (
                                        // Disabled items get pointer-events: none, so a tooltip can't
                                        // explain them — the reason renders inline instead.
                                        <span className="flex flex-col items-start text-left">
                                            <span>{option.name}</span>
                                            <span className="text-muted whitespace-normal">
                                                {METRIC_UNLINKABLE_REASON}
                                            </span>
                                        </span>
                                    ) : (
                                        option.name
                                    )}
                                </DropdownMenuCheckboxItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
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

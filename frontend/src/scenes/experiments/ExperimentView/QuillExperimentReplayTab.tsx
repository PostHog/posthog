import { Fragment } from 'react'

import { IconChevronDown, IconInfo } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

import { Experiment } from '~/types'

import { NOT_A_FUNNEL_REASON } from '../utils'
import { ExperimentBehaviorComparison, ExperimentBehaviorComparisonToggle } from './ExperimentBehaviorComparison'
import { EXPERIMENT_RECORDING_MODE_OPTIONS, METRIC_UNSELECTABLE_COPY } from './experimentRecordingModes'
import { ExperimentRecordingsListEmptyState } from './ExperimentRecordingsListEmptyState'
import {
    ALL_EXPOSED_CAPTION,
    ALL_SESSIONS_HELP,
    ALL_VARIANTS,
    LIST_UNAVAILABLE_COPY,
    METRIC_FILTER_HELP,
    bucketCaption,
    metricFilterTriggerLabel,
    unappliedModeReason,
    useExperimentReplayTab,
} from './ExperimentReplayTab'
import { type ExperimentReplayExposureScope } from './experimentReplayTabLogic'
import { ExperimentScannerEntryPoint } from './ExperimentScannerEntryPoint'
import { QuillHelpTooltip } from './QuillCardParts'
import { QuillVariantTag } from './QuillVariantTag'

function MetricOptionLabel({ name, eventNames }: { name: string; eventNames: string[] }): JSX.Element {
    return (
        <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate">{name}</span>
            {eventNames.length > 0 && (
                <Text size="xs" variant="muted" render={<span className="shrink-0" />}>
                    {eventNames.join(', ')}
                </Text>
            )}
        </span>
    )
}

export function QuillExperimentReplayTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const {
        effectiveVariantKey,
        effectiveExposureScope,
        exposureInSessionUnavailableReason,
        playlistHeldForChecks,
        variantKeys,
        recordingsFilters,
        effectiveMetricUuids,
        metricOptions,
        metricFilterMode,
        droppedMetricReason,
        filtersCustomized,
        sessionBucket,
        sessionBucketLoading,
        sessionBucketError,
        sessionBucketRequest,
        listUnavailableReason,
        listLoadError,
        setSelectedVariantKey,
        setExposureScope,
        setMetricSelected,
        setMetricFilterMode,
        loadSessionBucket,
        playlistFiltersChanged,
        recordingsLoaded,
        recordingsLoadFailed,
        recordingOpened,
        experimentScannerEnabled,
        inSessionCopy,
        playlistLogicProps,
        watchRecording,
        retryList,
        linkableMetricOptions,
        unselectableOptionsByReason,
        clientSideFilterApplied,
    } = useExperimentReplayTab(experiment)

    if (listUnavailableReason !== null) {
        const { dataAttr, copy } = LIST_UNAVAILABLE_COPY[listUnavailableReason]
        return (
            <Item variant="outline" size="sm" tone="info" data-attr={dataAttr}>
                <ItemMedia variant="icon" aria-hidden>
                    <IconInfo />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemDescription className="line-clamp-none">{copy}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    const scopeLockedReason = sessionBucketRequest !== null ? inSessionCopy.scopeLockedReason : undefined

    return (
        <div className="flex flex-col gap-2" data-attr="experiment-recordings-tab">
            {experimentScannerEnabled && (
                <ExperimentScannerEntryPoint experiment={experiment} variantKey={effectiveVariantKey} />
            )}
            <div className="flex flex-wrap items-center gap-2">
                <ToggleGroup
                    variant="outline"
                    size="sm"
                    value={[effectiveVariantKey ?? ALL_VARIANTS]}
                    onValueChange={(next: string[]) =>
                        next[0] && setSelectedVariantKey(next[0] === ALL_VARIANTS ? null : next[0])
                    }
                    aria-label="Variant"
                >
                    <ToggleGroupItem value={ALL_VARIANTS}>All</ToggleGroupItem>
                    {variantKeys.map((key) => (
                        <ToggleGroupItem key={key} value={key}>
                            <QuillVariantTag variantKey={key} />
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <span className="flex items-center gap-1">
                    <ToggleGroup
                        variant="outline"
                        size="sm"
                        value={[effectiveExposureScope]}
                        onValueChange={(next: string[]) =>
                            next[0] && setExposureScope(next[0] as ExperimentReplayExposureScope)
                        }
                        aria-label="Exposure scope"
                    >
                        <ToggleGroupItem
                            value="in_session"
                            disabledReason={scopeLockedReason ?? exposureInSessionUnavailableReason ?? undefined}
                            data-attr="experiment-recordings-exposure-scope-in-session"
                        >
                            Exposed in session
                        </ToggleGroupItem>
                        <ToggleGroupItem
                            value="all_exposed"
                            disabledReason={scopeLockedReason}
                            data-attr="experiment-recordings-exposure-scope-all"
                        >
                            All sessions
                        </ToggleGroupItem>
                    </ToggleGroup>
                    <QuillHelpTooltip
                        label="exposure scope"
                        help={
                            <span className="flex flex-col gap-2">
                                <span>
                                    <b>Exposed in session:</b> {inSessionCopy.tooltip}
                                </span>
                                <span>
                                    <b>All sessions:</b> {ALL_SESSIONS_HELP}
                                </span>
                            </span>
                        }
                    />
                </span>
                {metricOptions.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="sm"
                                    tooltip={METRIC_FILTER_HELP}
                                    data-attr="experiment-recordings-metric-filter"
                                />
                            }
                        >
                            {metricFilterTriggerLabel(metricFilterMode, effectiveMetricUuids, metricOptions)}
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-fit max-w-100">
                            <div className="p-1">
                                <ToggleGroup
                                    variant="outline"
                                    size="sm"
                                    className="w-full"
                                    value={[metricFilterMode]}
                                    onValueChange={(next: string[]) =>
                                        next[0] && setMetricFilterMode(next[0] as typeof metricFilterMode)
                                    }
                                    aria-label="Metric filter mode"
                                >
                                    {EXPERIMENT_RECORDING_MODE_OPTIONS.map((option) => (
                                        <ToggleGroupItem key={option.value} value={option.value} className="flex-1">
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            </div>
                            <DropdownMenuSeparator />
                            {linkableMetricOptions.map((option) => (
                                <DropdownMenuCheckboxItem
                                    key={option.uuid}
                                    checked={effectiveMetricUuids.includes(option.uuid)}
                                    onCheckedChange={(checked: boolean) => setMetricSelected(option.uuid, checked)}
                                    closeOnClick={false}
                                    data-attr="experiment-recordings-metric-option"
                                >
                                    <MetricOptionLabel name={option.name} eventNames={option.eventNames} />
                                </DropdownMenuCheckboxItem>
                            ))}
                            {[...unselectableOptionsByReason.entries()].map(([reason, options], index) => (
                                <Fragment key={reason}>
                                    {(linkableMetricOptions.length > 0 || index > 0) && <DropdownMenuSeparator />}
                                    <DropdownMenuGroup>
                                        <DropdownMenuLabel inset className="flex items-center gap-1">
                                            {reason === NOT_A_FUNNEL_REASON
                                                ? 'Needs a funnel metric'
                                                : "Can't match to recordings"}
                                            <QuillHelpTooltip label="why" help={reason} />
                                        </DropdownMenuLabel>
                                        {options.map((option) => (
                                            <DropdownMenuItem
                                                key={option.uuid}
                                                inset
                                                disabled
                                                data-attr="experiment-recordings-metric-option"
                                            >
                                                <MetricOptionLabel name={option.name} eventNames={option.eventNames} />
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuGroup>
                                </Fragment>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                <ExperimentBehaviorComparisonToggle experiment={experiment} />
            </div>
            <Text size="xs" variant="muted" render={<div className="flex flex-wrap items-center gap-2" />}>
                {listLoadError !== null ? (
                    <>
                        <span data-attr="experiment-recordings-list-error-caption">
                            Couldn't load recordings: {listLoadError.detail}
                        </span>
                        <Button
                            variant="outline"
                            size="xs"
                            onClick={retryList}
                            data-attr="experiment-recordings-list-retry"
                        >
                            Try again
                        </Button>
                    </>
                ) : clientSideFilterApplied ? null : droppedMetricReason && !filtersCustomized ? (
                    <span data-attr="experiment-recordings-dropped-metric-caption">
                        {METRIC_UNSELECTABLE_COPY[droppedMetricReason].onTab}
                    </span>
                ) : !sessionBucketRequest && metricFilterMode === 'fired_all' ? (
                    <span data-attr="experiment-recordings-population-caption">
                        {effectiveExposureScope === 'in_session' ? inSessionCopy.caption : ALL_EXPOSED_CAPTION}
                    </span>
                ) : !sessionBucketRequest ? (
                    <span>{unappliedModeReason(metricFilterMode)}</span>
                ) : sessionBucketError !== null ? (
                    <>
                        <span>Couldn't work out which sessions match this filter: {sessionBucketError}</span>
                        <Button variant="outline" size="xs" onClick={() => loadSessionBucket()}>
                            Try again
                        </Button>
                    </>
                ) : sessionBucketLoading || !sessionBucket ? (
                    <span>Finding matching sessions…</span>
                ) : (
                    <span data-attr="experiment-recordings-bucket-caption">
                        {bucketCaption(sessionBucket, experiment.start_date ?? null)}
                    </span>
                )}
            </Text>
            <ExperimentBehaviorComparison experiment={experiment} onWatchRecording={watchRecording} />
            <div className="SessionRecordingPlaylistHeightWrapper">
                {playlistHeldForChecks ? (
                    <Skeleton className="h-full w-full" />
                ) : (
                    <SessionRecordingsPlaylist
                        {...playlistLogicProps}
                        analyticsSource="experiment-recordings-tab"
                        filters={recordingsFilters}
                        resetToCallerFilters
                        onFiltersChange={(filters) => playlistFiltersChanged(filters)}
                        onRecordingsLoaded={(recordings, isFirstPage) => recordingsLoaded(recordings, isFirstPage)}
                        onRecordingsLoadFailed={(error, isFirstPage) => recordingsLoadFailed(error, isFirstPage)}
                        onRecordingSelected={(recordingId) => recordingOpened(recordingId)}
                        listEmptyState={<ExperimentRecordingsListEmptyState experiment={experiment} />}
                    />
                )}
            </div>
        </div>
    )
}

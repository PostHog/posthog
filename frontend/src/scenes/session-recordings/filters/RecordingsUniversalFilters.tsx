import { IconClock, IconEye, IconFilter, IconHide, IconPlus, IconRevert, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonButtonProps,
    LemonInput,
    LemonModal,
    LemonTabs,
    Popover,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { MaxTool } from 'scenes/max/MaxTool'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, ReplayTabs, UniversalFiltersGroup } from '~/types'

import { ReplayActiveHoursHeatMap } from '../components/ReplayActiveHoursHeatMap'
import { ReplayActiveScreensTable } from '../components/ReplayActiveScreensTable'
import { ReplayActiveUsersTable } from '../components/ReplayActiveUsersTable'
import { playerSettingsLogic, TimestampFormat } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { createPlaylist, updatePlaylist } from '../playlist/playlistUtils'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { DurationFilter } from './DurationFilter'
import { SavedFilters } from './SavedFilters'

function HideRecordingsMenu(): JSX.Element {
    const { hideViewedRecordings, hideRecordingsMenuLabelFor } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)

    return (
        <SettingsMenu
            highlightWhenActive={false}
            items={[
                {
                    label: hideRecordingsMenuLabelFor(false),
                    onClick: () => setHideViewedRecordings(false),
                    active: !hideViewedRecordings,
                    'data-attr': 'hide-viewed-recordings-show-all',
                },
                {
                    label: hideRecordingsMenuLabelFor('current-user'),
                    onClick: () => setHideViewedRecordings('current-user'),
                    active: hideViewedRecordings === 'current-user',
                    'data-attr': 'hide-viewed-recordings-hide-current-user',
                },
                {
                    label: hideRecordingsMenuLabelFor('any-user'),
                    onClick: () => setHideViewedRecordings('any-user'),
                    active: hideViewedRecordings === 'any-user',
                    'data-attr': 'hide-viewed-recordings-hide-any-user',
                },
            ]}
            icon={hideViewedRecordings ? <IconHide /> : <IconEye />}
            rounded={true}
            label={hideRecordingsMenuLabelFor(hideViewedRecordings)}
        />
    )
}

export const RecordingsUniversalFiltersTabs = ({
    filters,
    setFilters,
    totalFiltersCount,
    className,
    allowReplayHogQLFilters = false,
    allowReplayGroupsFilters = false,
    resetFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    className?: string
    allowReplayHogQLFilters?: boolean
    allowReplayGroupsFilters?: boolean
}): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const durationFilter = filters.duration[0]

    const { activeFilterTab } = useValues(playlistLogic)
    const { setActiveFilterTab } = useActions(playlistLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.Replay,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.SessionProperties,
    ]

    if (allowReplayHogQLFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.HogQLExpression)
    }

    if (allowReplayGroupsFilters) {
        taxonomicGroupTypes.push(...groupsTaxonomicTypes)
    }

    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    const { savedFilters, appliedSavedFilter, showSavedFiltersBlock } = useValues(savedFiltersLogic)
    const { loadSavedFilters, setShowSavedFiltersBlock, setAppliedSavedfilter } = useActions(savedFiltersLogic)

    const [savedFilterName, setSavedFilterName] = useState(appliedSavedFilter ? appliedSavedFilter.name : '')

    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const createSavedFilter = async (): Promise<void> => {
        const res = await createPlaylist({ name: savedFilterName, filters, type: 'filters' }, false, false)
        if (res) {
            setAppliedSavedfilter(res)
        }
        reportRecordingPlaylistCreated('new')
        loadSavedFilters()
        setSavedFilterName('')
        setShowSavedFiltersBlock(false)
    }

    const tabs = [
        {
            key: 'filters',
            label: <div className="px-2">Filters</div>,
            content: (
                <div className={clsx('relative bg-surface-primary w-full ', className)}>
                    <div className="flex justify-between px-2 py-2 flex-wrap gap-1">
                        <AndOrFilterSelect
                            value={filters.filter_group.type}
                            onChange={(type) => {
                                let values = filters.filter_group.values

                                // set the type on the nested child when only using a single filter group
                                const hasSingleGroup = values.length === 1
                                if (hasSingleGroup) {
                                    const group = values[0] as UniversalFiltersGroup
                                    values = [{ ...group, type }]
                                }

                                setFilters({
                                    filter_group: {
                                        type: type,
                                        values: values,
                                    },
                                })
                            }}
                            topLevelFilter={true}
                            suffix={['filter', 'filters']}
                            size="small"
                        />
                        <div>
                            <TestAccountFilter
                                size="small"
                                filters={filters}
                                onChange={(testFilters) =>
                                    setFilters({
                                        filter_test_accounts: testFilters.filter_test_accounts,
                                    })
                                }
                            />
                        </div>
                    </div>
                    {!featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST] && (
                        <div className="flex justify-between px-2 py-2 flex-wrap gap-1">
                            <div className="flex flex-wrap gap-2 items-center">
                                <DateFilter
                                    dateFrom={filters.date_from ?? '-3d'}
                                    dateTo={filters.date_to}
                                    onChange={(changedDateFrom, changedDateTo) => {
                                        setFilters({
                                            date_from: changedDateFrom,
                                            date_to: changedDateTo,
                                        })
                                    }}
                                    dateOptions={[
                                        { key: 'Custom', values: [] },
                                        { key: 'Last 24 hours', values: ['-24h'] },
                                        { key: 'Last 3 days', values: ['-3d'] },
                                        { key: 'Last 7 days', values: ['-7d'] },
                                        { key: 'Last 30 days', values: ['-30d'] },
                                        { key: 'All time', values: ['-90d'] },
                                    ]}
                                    dropdownPlacement="bottom-start"
                                    size="small"
                                    // we always want to include the time in the date when setting it
                                    allowTimePrecision={true}
                                    // we always want to present the time control
                                    forceGranularity="minute"
                                />
                                <DurationFilter
                                    onChange={(newRecordingDurationFilter, newDurationType) => {
                                        setFilters({
                                            duration: [
                                                {
                                                    ...newRecordingDurationFilter,
                                                    key: newDurationType,
                                                },
                                            ],
                                        })
                                    }}
                                    recordingDurationFilter={durationFilter}
                                    durationTypeFilter={durationFilter.key}
                                    pageKey="session-recordings"
                                    size="small"
                                />
                            </div>
                        </div>
                    )}
                    <div className="flex flex-wrap gap-2 p-2">
                        <UniversalFilters
                            rootKey="session-recordings"
                            group={filters.filter_group}
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                        >
                            <RecordingsUniversalFilterGroup
                                size="small"
                                totalFiltersCount={totalFiltersCount}
                                resetFilters={resetFilters}
                                filters={filters}
                                setFilters={setFilters}
                            />
                        </UniversalFilters>
                    </div>
                    {(totalFiltersCount ?? 0) > 0 && showSavedFiltersBlock && (
                        <div className="flex gap-2 p-2 justify-start max-w-96">
                            <LemonInput
                                value={savedFilterName}
                                placeholder="Saved filter name"
                                onChange={setSavedFilterName}
                                size="xsmall"
                                autoFocus
                                fullWidth
                                onClick={(e) => {
                                    e.stopPropagation() // Prevent dropdown from closing
                                }}
                            />
                            <LemonButton type="primary" size="xsmall" onClick={() => void createSavedFilter()}>
                                Save
                            </LemonButton>
                        </div>
                    )}
                </div>
            ),
        },
        {
            key: 'saved',
            label: (
                <div className="px-2 flex">
                    <span>
                        {savedFilters.results?.length ? (
                            <LemonBadge.Number count={savedFilters.results?.length} className="mr-2" />
                        ) : null}
                    </span>
                    <span>Saved filters</span>
                </div>
            ),
            content: <SavedFilters setFilters={setFilters} />,
        },
    ]

    if (featureFlags[FEATURE_FLAGS.REPLAY_ACTIVE_HOURS_HEATMAP] === 'templates') {
        tabs.push({
            key: 'explore',
            label: <div className="px-2">Explore</div>,
            content: (
                <div className="flex flex-col gap-2 w-full pb-2">
                    <div className="flex flex-row gap-2 w-full">
                        <ReplayActiveUsersTable />
                        <ReplayActiveScreensTable />
                    </div>
                    <ReplayActiveHoursHeatMap />
                </div>
            ),
        })
    }

    return (
        <LemonTabs
            activeKey={activeFilterTab}
            onChange={(activeKey) => setActiveFilterTab(activeKey)}
            size="small"
            tabs={tabs}
        />
    )
}

export const RecordingsUniversalFiltersContent = ({
    filters,
    setFilters,
    resetFilters,
    totalFiltersCount,
    allowReplayHogQLFilters = false,
    allowReplayGroupsFilters = false,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    allowReplayHogQLFilters?: boolean
    allowReplayGroupsFilters?: boolean
}): JSX.Element => {
    const { setIsFiltersExpanded } = useActions(playlistLogic)

    return (
        <div className="bg-white p-2 h-full">
            <div className="flex justify-end items-center">
                <LemonButton icon={<IconX />} size="small" onClick={() => setIsFiltersExpanded(false)} />
            </div>
            <RecordingsUniversalFiltersTabs
                filters={filters}
                setFilters={setFilters}
                totalFiltersCount={totalFiltersCount}
                allowReplayHogQLFilters={allowReplayHogQLFilters}
                allowReplayGroupsFilters={allowReplayGroupsFilters}
                resetFilters={resetFilters}
            />
        </div>
    )
}

export const RecordingsUniversalFilters = ({
    filters,
    setFilters,
    resetFilters,
    totalFiltersCount,
    allowReplayHogQLFilters = false,
    allowReplayGroupsFilters = false,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    allowReplayHogQLFilters?: boolean
    allowReplayGroupsFilters?: boolean
}): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const { isFiltersExpanded } = useValues(playlistLogic)
    const { setIsFiltersExpanded } = useActions(playlistLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.Replay,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.SessionProperties,
    ]

    if (allowReplayHogQLFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.HogQLExpression)
    }

    if (allowReplayGroupsFilters) {
        taxonomicGroupTypes.push(...groupsTaxonomicTypes)
    }

    const { featureFlags } = useValues(featureFlagLogic)

    const MaxToolContent = (): JSX.Element => {
        // if the feature flag is enabled, we want to show only the button
        if (featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST]) {
            return (
                <MaxTool
                    name="search_session_recordings"
                    displayName="Search recordings"
                    context={{
                        current_filters: filters,
                    }}
                    callback={(toolOutput: Record<string, any>) => {
                        // Improve type
                        setFilters(toolOutput)
                        setIsFiltersExpanded(true)
                    }}
                    initialMaxPrompt="Show me recordings where "
                    suggestions={[
                        'Show recordings of people who visited signup in the last 24 hours',
                        'Show recordings showing user frustration',
                        'Show recordings of people who faced bugs',
                    ]}
                    onMaxOpen={() => setIsFiltersExpanded(false)}
                >
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconFilter />}
                            onClick={() => {
                                setIsFiltersExpanded(!isFiltersExpanded)
                            }}
                            fullWidth
                        >
                            Filters
                        </LemonButton>
                    </>
                </MaxTool>
            )
        }

        return (
            <MaxTool
                name="search_session_recordings"
                displayName="Search recordings"
                context={{
                    current_filters: filters,
                }}
                callback={(toolOutput: Record<string, any>) => {
                    // Improve type
                    setFilters(toolOutput)
                    setIsFiltersExpanded(true)
                }}
                initialMaxPrompt="Show me recordings where "
                suggestions={[
                    'Show recordings of people who visited signup in the last 24 hours',
                    'Show recordings showing user frustration',
                    'Show recordings of people who faced bugs',
                ]}
                onMaxOpen={() => setIsFiltersExpanded(false)}
            >
                <>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFilter />}
                        onClick={() => {
                            setIsFiltersExpanded(!isFiltersExpanded)
                        }}
                        fullWidth
                    >
                        Filters
                    </LemonButton>
                    <LemonModal
                        isOpen={isFiltersExpanded}
                        onClose={(): void => {
                            setIsFiltersExpanded(false)
                        }}
                        width={750}
                        footer={
                            <div className="flex justify-end p-2 gap-2">
                                <LemonButton type="primary" size="small" onClick={() => setIsFiltersExpanded(false)}>
                                    Close
                                </LemonButton>
                            </div>
                        }
                    >
                        <RecordingsUniversalFiltersTabs
                            filters={filters}
                            setFilters={setFilters}
                            resetFilters={resetFilters}
                            totalFiltersCount={totalFiltersCount}
                            allowReplayHogQLFilters={allowReplayHogQLFilters}
                            allowReplayGroupsFilters={allowReplayGroupsFilters}
                        />
                    </LemonModal>
                </>
            </MaxTool>
        )
    }

    return (
        <>
            <MaxToolContent />
            <div className="flex gap-2 mt-2 justify-between">
                <HideRecordingsMenu />
                <SettingsMenu
                    highlightWhenActive={false}
                    items={[
                        {
                            label: 'UTC',
                            onClick: () => setPlaylistTimestampFormat(TimestampFormat.UTC),
                            active: playlistTimestampFormat === TimestampFormat.UTC,
                        },
                        {
                            label: 'Device',
                            onClick: () => setPlaylistTimestampFormat(TimestampFormat.Device),
                            active: playlistTimestampFormat === TimestampFormat.Device,
                        },
                        {
                            label: 'Relative',
                            onClick: () => setPlaylistTimestampFormat(TimestampFormat.Relative),
                            active: playlistTimestampFormat === TimestampFormat.Relative,
                        },
                    ]}
                    icon={<IconClock />}
                    label={TimestampFormatToLabel[playlistTimestampFormat]}
                    rounded={true}
                />
            </div>
        </>
    )
}

const RecordingsUniversalFilterGroup = ({
    size = 'small',
    totalFiltersCount,
    resetFilters,
    filters,
    setFilters,
}: {
    size?: LemonButtonProps['size']
    totalFiltersCount?: number
    resetFilters?: () => void
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)
    const [isPopoverVisible, setIsPopoverVisible] = useState(false)
    const durationFilter = filters.duration[0]

    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })

    const { setAppliedSavedfilter, loadSavedFilters, setSavedFilterName, setShowSavedFiltersBlock } =
        useActions(savedFiltersLogic)
    const { savedFilters, appliedSavedFilter, savedFilterName, showSavedFiltersBlock } = useValues(savedFiltersLogic)
    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)

    const updateSavedFilter = async (): Promise<void> => {
        if (appliedSavedFilter === null) {
            return
        }

        await updatePlaylist(appliedSavedFilter.short_id, { name: savedFilterName, filters, type: 'filters' }, false)
        reportRecordingPlaylistCreated('new')
        loadSavedFilters()
        setSavedFilterName('')
    }

    useEffect(() => {
        setAllowInitiallyOpen(true)
    }, [])

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <div className="w-full">
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            {featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST] && (
                                <div className="flex flex-wrap items-center gap-2 mb-4">
                                    <DateFilter
                                        dateFrom={filters.date_from ?? '-3d'}
                                        dateTo={filters.date_to}
                                        onChange={(changedDateFrom, changedDateTo) => {
                                            setFilters({
                                                date_from: changedDateFrom,
                                                date_to: changedDateTo,
                                            })
                                        }}
                                        dateOptions={[
                                            { key: 'Custom', values: [] },
                                            { key: 'Last 24 hours', values: ['-24h'] },
                                            { key: 'Last 3 days', values: ['-3d'] },
                                            { key: 'Last 7 days', values: ['-7d'] },
                                            { key: 'Last 30 days', values: ['-30d'] },
                                            { key: 'All time', values: ['-90d'] },
                                        ]}
                                        dropdownPlacement="bottom-start"
                                        size="small"
                                        // we always want to include the time in the date when setting it
                                        allowTimePrecision={true}
                                        // we always want to present the time control
                                        forceGranularity="minute"
                                    />
                                    <DurationFilter
                                        onChange={(newRecordingDurationFilter, newDurationType) => {
                                            setFilters({
                                                duration: [
                                                    {
                                                        ...newRecordingDurationFilter,
                                                        key: newDurationType,
                                                    },
                                                ],
                                            })
                                        }}
                                        recordingDurationFilter={durationFilter}
                                        durationTypeFilter={durationFilter.key}
                                        pageKey="session-recordings"
                                        size="small"
                                    />
                                    <Popover
                                        overlay={<UniversalFilters.PureTaxonomicFilter />}
                                        placement="bottom"
                                        visible={isPopoverVisible}
                                        onClickOutside={() => setIsPopoverVisible(false)}
                                    >
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            icon={<IconPlus />}
                                            onClick={() => setIsPopoverVisible(!isPopoverVisible)}
                                        >
                                            Add filter
                                        </LemonButton>
                                    </Popover>
                                </div>
                            )}
                            <div className="flex flex-wrap items-center gap-2 py-4">
                                {(totalFiltersCount ?? 0) > 0 ? (
                                    <span className="font-semibold">Applied filters:</span>
                                ) : (
                                    featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST] && (
                                        <div className="text-sm text-text-secondary p-4 border rounded w-full flex justify-center items-center gap-2">
                                            <FilmCameraHog className="w-24 h-24" />
                                            <div className="flex flex-col gap-2">
                                                <h2 className="font-semibold">No filters applied</h2>
                                                <p>Apply filters to find interesting recordings. You can filter by:</p>
                                                <ul className="list-disc list-inside text-sm ml-4">
                                                    <li>Date</li>
                                                    <li>Duration</li>
                                                    <li>Events & Event properties</li>
                                                    <li>Actions</li>
                                                    <li>Cohorts</li>
                                                    <li>Person properties</li>
                                                    <li>Session properties</li>
                                                    <li>HogQL expressions</li>
                                                    <li>Test accounts</li>
                                                    <li>Groups</li>
                                                    <li>and more...</li>
                                                </ul>
                                            </div>
                                        </div>
                                    )
                                )}
                                <RecordingsUniversalFilterGroup
                                    size={size}
                                    totalFiltersCount={totalFiltersCount}
                                    resetFilters={resetFilters}
                                    filters={filters}
                                    setFilters={setFilters}
                                />
                                {(totalFiltersCount ?? 0) > 0 && resetFilters && (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            onClick={() => {
                                                if (resetFilters) {
                                                    void resetFilters()
                                                    setAppliedSavedfilter(null)
                                                }
                                            }}
                                            icon={<IconRevert />}
                                            tooltip="Reset any changes you've made to the filters"
                                        >
                                            Reset filters
                                        </LemonButton>
                                        {appliedSavedFilter !== null &&
                                        savedFilters.results?.find((filter) => equal(filter.filters, filters)) ===
                                            undefined ? (
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                onClick={() => void updateSavedFilter()}
                                                sideAction={{
                                                    dropdown: {
                                                        placement: 'bottom-end',
                                                        overlay: (
                                                            <LemonMenuOverlay
                                                                items={[
                                                                    {
                                                                        label: 'Save as...',
                                                                        onClick: () =>
                                                                            setShowSavedFiltersBlock(
                                                                                !showSavedFiltersBlock
                                                                            ),
                                                                    },
                                                                ]}
                                                            />
                                                        ),
                                                    },
                                                }}
                                            >
                                                Update "{appliedSavedFilter.name}" filter
                                            </LemonButton>
                                        ) : (
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                onClick={() => setShowSavedFiltersBlock(!showSavedFiltersBlock)}
                                            >
                                                {appliedSavedFilter === null ? 'Save filters' : 'Save as new filter'}
                                            </LemonButton>
                                        )}
                                    </>
                                )}
                            </div>
                            {!featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST] && (
                                <>
                                    <div className="font-semibold mb-1">Add filter:</div>
                                    <UniversalFilters.PureTaxonomicFilter />
                                </>
                            )}
                        </UniversalFilters.Group>
                    </div>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen}
                        metadataSource={{ kind: NodeKind.RecordingsQuery }}
                    />
                )
            })}
        </>
    )
}

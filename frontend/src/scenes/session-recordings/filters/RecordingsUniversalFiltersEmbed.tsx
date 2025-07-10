import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconClock, IconEye, IconFilter, IconHide, IconPlus, IconRevert, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonInput, LemonModal, LemonTab, LemonTabs, Popover } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { MaxTool } from 'scenes/max/MaxTool'
import { maxLogic } from 'scenes/max/maxLogic'
import { maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/schema'
import { RecordingUniversalFilters, ReplayTabs, SidePanelTab, UniversalFiltersGroup } from '~/types'

import { ReplayActiveHoursHeatMap } from '../components/ReplayActiveHoursHeatMap'
import { ReplayActiveScreensTable } from '../components/ReplayActiveScreensTable'
import { ReplayActiveUsersTable } from '../components/ReplayActiveUsersTable'
import { TimestampFormat, playerSettingsLogic } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { createPlaylist, updatePlaylist } from '../playlist/playlistUtils'
import { defaultRecordingDurationFilter } from '../playlist/sessionRecordingsPlaylistLogic'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { DurationFilter } from './DurationFilter'
import { SavedFilters } from './SavedFilters'

function HideRecordingsMenu(): JSX.Element {
    const { hideViewedRecordings, hideRecordingsMenuLabelFor } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const items = [
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
    ]

    // If the person wished to be excluded from the hide recordings menu, we don't show the option to hide recordings that other people have watched
    if (!featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]) {
        items.push({
            label: hideRecordingsMenuLabelFor('any-user'),
            onClick: () => setHideViewedRecordings('any-user'),
            active: hideViewedRecordings === 'any-user',
            'data-attr': 'hide-viewed-recordings-hide-any-user',
        })
    }

    return (
        <SettingsMenu
            highlightWhenActive={false}
            items={items}
            icon={hideViewedRecordings ? <IconHide /> : <IconEye />}
            rounded={true}
            label={hideRecordingsMenuLabelFor(hideViewedRecordings)}
        />
    )
}

export const RecordingsUniversalFiltersEmbedButton = ({
    filters,
    setFilters,
    totalFiltersCount,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    totalFiltersCount?: number
}): JSX.Element => {
    const { isFiltersExpanded } = useValues(playlistLogic)
    const { setIsFiltersExpanded } = useActions(playlistLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)
    const { isZenMode } = useValues(playerSettingsLogic)

    return (
        <>
            <MaxTool
                name="search_session_recordings"
                displayName="Search recordings"
                description="Max can set up filters for the recordings list"
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
                        active={isFiltersExpanded}
                        type="secondary"
                        size="small"
                        icon={<IconFilter />}
                        onClick={() => {
                            setIsFiltersExpanded(!isFiltersExpanded)
                        }}
                        fullWidth
                        data-attr="filter-recordings-button"
                    >
                        {isFiltersExpanded ? 'Hide' : 'Show'} filters{' '}
                        {totalFiltersCount ? <LemonBadge.Number count={totalFiltersCount} size="small" /> : null}
                    </LemonButton>
                </>
            </MaxTool>
            {!isZenMode && (
                <div className="mt-2 flex justify-between gap-2">
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
            )}
        </>
    )
}

export const RecordingsUniversalFiltersEmbed = ({
    filters,
    setFilters,
    resetFilters,
    totalFiltersCount,
    className,
    allowReplayHogQLFilters = false,
    allowReplayGroupsFilters = false,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    className?: string
    allowReplayHogQLFilters?: boolean
    allowReplayGroupsFilters?: boolean
}): JSX.Element => {
    const [isSaveFiltersModalOpen, setIsSaveFiltersModalOpen] = useState(false)
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: threadLogicKey, conversation }))
    const { openSidePanel } = useActions(sidePanelSettingsLogic)

    const [savedFilterName, setSavedFilterName] = useState('')
    const { featureFlags } = useValues(featureFlagLogic)
    const [searchQuery, setSearchQuery] = useState('')

    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const durationFilter = filters.duration?.[0] ?? defaultRecordingDurationFilter

    const { activeFilterTab } = useValues(playlistLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistLogic)
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

    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { savedFilters, appliedSavedFilter } = useValues(savedFiltersLogic)
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(savedFiltersLogic)

    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)

    const addSavedFilter = async (): Promise<void> => {
        const f = await createPlaylist({ name: savedFilterName, filters, type: 'filters' }, false)
        reportRecordingPlaylistCreated('new')
        loadSavedFilters()
        setIsSaveFiltersModalOpen(false)
        setSavedFilterName('')
        setAppliedSavedFilter(f)
    }

    const updateSavedFilter = async (): Promise<void> => {
        if (appliedSavedFilter === null) {
            return
        }

        const f = await updatePlaylist(appliedSavedFilter.short_id, { filters, type: 'filters' }, false)
        loadSavedFilters()
        setAppliedSavedFilter(f)
    }

    const handleMaxOpen = (): void => {
        openSidePanel(SidePanelTab.Max)
        askMax(searchQuery)
        setSearchQuery('')
    }

    const closeSaveFiltersModal = (): void => {
        setIsSaveFiltersModalOpen(false)
        setSavedFilterName('')
    }

    const handleResetFilters = (): void => {
        resetFilters?.()
        setAppliedSavedFilter(null)
    }

    const SaveFiltersModal = (): JSX.Element => {
        return (
            <LemonModal
                title="Save filters for later"
                description="You can access them on 'Saved filters' tab"
                isOpen={isSaveFiltersModalOpen}
                onClose={closeSaveFiltersModal}
            >
                <div>
                    <LemonInput
                        value={savedFilterName}
                        placeholder="Saved filter name"
                        onChange={setSavedFilterName}
                        size="small"
                        autoFocus
                        fullWidth
                        onClick={(e) => {
                            e.stopPropagation() // Prevent dropdown from closing
                        }}
                    />
                    <div className="mt-4 flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={closeSaveFiltersModal} tooltip="Close">
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={savedFilterName.length === 0 ? 'Enter a name' : undefined}
                            onClick={() => void addSavedFilter()}
                        >
                            Save filters
                        </LemonButton>
                    </div>
                </div>
            </LemonModal>
        )
    }

    const tabs: LemonTab<string>[] = [
        {
            key: 'filters',
            label: <div className="px-2">Filters</div>,
            content: (
                <div className={clsx('bg-surface-primary relative w-full', className)}>
                    {featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST_MAX_AI] && (
                        <>
                            <div className="mt-4 px-2 py-2 text-center">
                                <h2 className="@md/max-welcome:text-2xl mb-2 text-balance text-xl font-bold">
                                    Ask Max AI
                                </h2>
                                <p className="text-secondary text-sm">
                                    Ask Max AI to help you find recordings that match your criteria.
                                </p>
                            </div>
                            <div className="mx-auto flex max-w-2xl items-center gap-2 px-2">
                                <LemonInput
                                    placeholder="Show me recordings of people who ..."
                                    size="small"
                                    fullWidth
                                    onChange={setSearchQuery}
                                    onPressEnter={handleMaxOpen}
                                />
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    disabledReason={searchQuery.length === 0 ? 'Enter a search query' : undefined}
                                    icon={<IconArrowRight />}
                                    onClick={handleMaxOpen}
                                />
                            </div>
                            <div className="text-secondary my-4 flex items-center justify-center gap-2 px-2 py-2 text-xs font-medium">
                                <div className="bg-border h-px flex-1" />
                                <span>Or set filters manually</span>
                                <div className="bg-border h-px flex-1" />
                            </div>
                        </>
                    )}
                    <div className="flex items-center justify-between py-2">
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
                        <div className="mr-2">
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

                    <div className="mt-2 flex flex-wrap justify-between gap-2 px-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="py-2 font-medium">Applied filters:</div>
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
                            <UniversalFilters
                                rootKey="session-recordings"
                                group={filters.filter_group}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                            >
                                <RecordingsUniversalFilterGroup />
                            </UniversalFilters>
                        </div>
                    </div>
                    <div className="mx-2 mt-8 flex justify-between gap-2 border-t pt-4">
                        <div className="flex flex-wrap items-center justify-end gap-2">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={handleResetFilters}
                                icon={<IconRevert />}
                                tooltip="Reset any changes you've made to the filters"
                                disabledReason={
                                    !(resetFilters && (totalFiltersCount ?? 0) > 0) ? 'No filters applied' : undefined
                                }
                            >
                                Reset filters
                            </LemonButton>
                            {appliedSavedFilter ? (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => void updateSavedFilter()}
                                    tooltip="Update saved filter"
                                    disabledReason={
                                        equal(appliedSavedFilter.filters, filters) ? 'No changes to update' : undefined
                                    }
                                    sideAction={{
                                        dropdown: {
                                            placement: 'bottom-end',
                                            overlay: (
                                                <LemonMenuOverlay
                                                    items={[
                                                        {
                                                            label: 'Save as a new filter',
                                                            onClick: () => setIsSaveFiltersModalOpen(true),
                                                        },
                                                    ]}
                                                />
                                            ),
                                        },
                                    }}
                                >
                                    Update "{appliedSavedFilter.name || 'Unnamed'}"
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => setIsSaveFiltersModalOpen(true)}
                                    disabledReason={(totalFiltersCount ?? 0) === 0 ? 'No filters applied' : undefined}
                                    tooltip="Save filters for later"
                                >
                                    Add to "Saved filters"
                                </LemonButton>
                            )}
                        </div>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => setIsFiltersExpanded(false)}
                            tooltip="Close filters and start watching recordings"
                        >
                            {(totalFiltersCount ?? 0) === 0 ? 'Close filters' : 'Start watching'}
                        </LemonButton>
                    </div>
                    {SaveFiltersModal()}
                </div>
            ),
            'data-attr': 'session-recordings-filters-tab',
        },
        {
            key: 'saved',
            label: (
                <div className="flex px-2">
                    <span>
                        {savedFilters.results?.length ? (
                            <LemonBadge.Number count={savedFilters.results?.length} className="mr-2" />
                        ) : null}
                    </span>
                    <span>Saved filters</span>
                </div>
            ),
            content: <SavedFilters setFilters={setFilters} />,
            'data-attr': 'session-recordings-saved-tab',
        },
        {
            key: 'explore',
            label: <div className="px-2">Explore</div>,
            content: (
                <div className="flex w-full flex-col gap-2 pb-2">
                    <div className="flex w-full flex-row gap-2">
                        <ReplayActiveUsersTable />
                        <ReplayActiveScreensTable />
                    </div>
                    <ReplayActiveHoursHeatMap />
                </div>
            ),
            'data-attr': 'session-recordings-explore-tab',
        },
    ]

    return (
        <div className="relative">
            <div className="z-1 absolute right-0 top-0">
                <LemonButton icon={<IconX />} size="small" onClick={() => setIsFiltersExpanded(false)} />
            </div>
            <LemonTabs
                activeKey={activeFilterTab}
                onChange={(activeKey) => setActiveFilterTab(activeKey)}
                size="small"
                tabs={tabs}
            />
        </div>
    )
}

const RecordingsUniversalFilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)
    const [isPopoverVisible, setIsPopoverVisible] = useState(false)
    useEffect(() => {
        setAllowInitiallyOpen(true)
    }, [])

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <RecordingsUniversalFilterGroup />

                        <Popover
                            overlay={<UniversalFilters.PureTaxonomicFilter fullWidth={false} />}
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
                    </UniversalFilters.Group>
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

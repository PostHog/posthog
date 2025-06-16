import { IconArrowRight, IconClock, IconFilter, IconPlus, IconRevert, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonButtonProps,
    LemonInput,
    LemonModal,
    LemonTab,
    LemonTabs,
    Popover,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { maxLogic } from 'scenes/max/maxLogic'
import { maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, ReplayTabs, SidePanelTab, UniversalFiltersGroup } from '~/types'

import { ReplayActiveHoursHeatMap } from '../components/ReplayActiveHoursHeatMap'
import { ReplayActiveScreensTable } from '../components/ReplayActiveScreensTable'
import { ReplayActiveUsersTable } from '../components/ReplayActiveUsersTable'
import { playerSettingsLogic, TimestampFormat } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { createPlaylist, updatePlaylist } from '../playlist/playlistUtils'
import { defaultRecordingDurationFilter } from '../playlist/sessionRecordingsPlaylistLogic'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { DurationFilter } from './DurationFilter'
import { HideRecordingsMenu } from './RecordingsUniversalFilters'
import { SavedFilters } from './SavedFilters'

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

    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
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
                    <div className="flex justify-end gap-2 mt-4">
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
                <div className={clsx('relative bg-surface-primary w-full ', className)}>
                    {featureFlags[FEATURE_FLAGS.REPLAY_FILTERS_IN_PLAYLIST_MAX_AI] && (
                        <>
                            <div className="px-2 py-2 text-center mt-4">
                                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">
                                    Ask Max AI
                                </h2>
                                <p className="text-secondary text-sm">
                                    Ask Max AI to help you find recordings that match your criteria.
                                </p>
                            </div>
                            <div className="flex items-center gap-2 px-2 max-w-2xl mx-auto">
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
                            <div className="px-2 py-2 font-medium flex items-center justify-center gap-2 text-secondary text-xs my-4">
                                <div className="h-px bg-border flex-1" />
                                <span>Or set filters manually</span>
                                <div className="h-px bg-border flex-1" />
                            </div>
                        </>
                    )}
                    <div className="flex items-center py-2 justify-between">
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

                    <div className="flex justify-between flex-wrap gap-2 px-2 mt-2">
                        <div className="flex flex-wrap gap-2 items-center">
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
                                <RecordingsUniversalFilterGroup size="small" totalFiltersCount={totalFiltersCount} />
                            </UniversalFilters>
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2 items-center mt-8 justify-end border-t pt-4 mx-2">
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
                                type="primary"
                                size="small"
                                onClick={() => setIsSaveFiltersModalOpen(true)}
                                disabledReason={(totalFiltersCount ?? 0) === 0 ? 'No filters applied' : undefined}
                                tooltip="Save filters for later"
                            >
                                Save filters
                            </LemonButton>
                        )}
                    </div>
                    {SaveFiltersModal()}
                </div>
            ),
            'data-attr': 'session-recordings-filters-tab',
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
            'data-attr': 'session-recordings-saved-tab',
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
            'data-attr': 'session-recordings-explore-tab',
        })
    }

    return (
        <div className="relative">
            <div className="absolute top-0 right-0 z-1">
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

const RecordingsUniversalFilterGroup = ({
    size = 'small',
    totalFiltersCount,
}: {
    size?: LemonButtonProps['size']
    totalFiltersCount?: number
}): JSX.Element => {
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
                        <RecordingsUniversalFilterGroup size={size} totalFiltersCount={totalFiltersCount} />

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

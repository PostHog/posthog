import { IconArrowRight, IconClock, IconEye, IconFilter, IconHide, IconPlus, IconRevert, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonButtonProps, LemonInput, LemonTabs, Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
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
import { createPlaylist } from '../playlist/playlistUtils'
import { defaultRecordingDurationFilter } from '../playlist/sessionRecordingsPlaylistLogic'
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

export const RecordingsUniversalFiltersEmbedButton = ({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element => {
    const { isFiltersExpanded } = useValues(playlistLogic)
    const { setIsFiltersExpanded } = useActions(playlistLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)

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
    const { savedFilters } = useValues(savedFiltersLogic)
    const { loadSavedFilters } = useActions(savedFiltersLogic)

    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)

    const newPlaylistHandler = async (): Promise<void> => {
        await createPlaylist({ name: savedFilterName, filters, type: 'filters' }, false)
        reportRecordingPlaylistCreated('new')
        loadSavedFilters()
        setSavedFilterName('')
    }

    const handleMaxOpen = (): void => {
        openSidePanel(SidePanelTab.Max)
        askMax(searchQuery)
        setSearchQuery('')
    }

    const tabs = [
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
                    <div className="px-2 py-2 font-medium">Applied filters:</div>
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
                            <UniversalFilters
                                rootKey="session-recordings"
                                group={filters.filter_group}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                            >
                                <RecordingsUniversalFilterGroup size="small" totalFiltersCount={totalFiltersCount} />
                            </UniversalFilters>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={resetFilters}
                                icon={<IconRevert />}
                                tooltip="Reset any changes you've made to the filters"
                                disabledReason={
                                    !(resetFilters && (totalFiltersCount ?? 0) > 0) ? 'No filters applied' : undefined
                                }
                            >
                                Reset filters
                            </LemonButton>
                        </div>
                    </div>
                    {(totalFiltersCount ?? 0) > 0 && (
                        <div className="flex gap-2 p-2 justify-start">
                            {savedFilters.results?.find((filter) => equal(filter.filters, filters)) ? (
                                <div className="text-sm italic text-text-secondary inline-flex items-center font-medium gap-1">
                                    "
                                    {savedFilters.results?.find((filter) => equal(filter.filters, filters))?.name ||
                                        'Unnamed'}
                                    " saved filter applied
                                </div>
                            ) : (
                                <>
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
                                    <LemonButton type="primary" size="xsmall" onClick={() => void newPlaylistHandler()}>
                                        Save filters
                                    </LemonButton>
                                </>
                            )}
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
                            overlay={<UniversalFilters.PureTaxonomicFilter isWide={false} />}
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

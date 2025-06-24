import { IconClock, IconEye, IconFilter, IconHide, IconRevert } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonButtonProps, LemonInput, LemonModal, LemonTabs } from '@posthog/lemon-ui'
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
import { MaxTool } from 'scenes/max/MaxTool'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, ReplayTabs, UniversalFiltersGroup } from '~/types'

import { playerSettingsLogic, TimestampFormat } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { createPlaylist } from '../playlist/playlistUtils'
import { defaultRecordingDurationFilter } from '../playlist/sessionRecordingsPlaylistLogic'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { DurationFilter } from './DurationFilter'
import { SavedFilters } from './SavedFilters'

export function HideRecordingsMenu(): JSX.Element {
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

export const RecordingsUniversalFilters = ({
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
    const [savedFilterName, setSavedFilterName] = useState('')

    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const durationFilter = filters.duration?.[0] ?? defaultRecordingDurationFilter

    const { isFiltersExpanded, activeFilterTab } = useValues(playlistLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { isZenMode } = useValues(playerSettingsLogic)

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

    /** Modal footer with buttons for reset and close */
    const ModalFooter = (): JSX.Element => {
        return (
            <div className="flex justify-between p-2 gap-2">
                {activeFilterTab === 'filters' && (
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
                )}
                <LemonButton type="primary" size="small" onClick={() => setIsFiltersExpanded(false)}>
                    Close
                </LemonButton>
            </div>
        )
    }

    const tabs = [
        {
            key: 'filters',
            label: <div className="px-2">Filters</div>,
            content: (
                <div className={clsx('relative bg-surface-primary w-full ', className)}>
                    <div className="flex items-center py-2">
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
                    </div>
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
                    <div className="flex flex-wrap gap-2 p-2">
                        <UniversalFilters
                            rootKey="session-recordings"
                            group={filters.filter_group}
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                        >
                            <RecordingsUniversalFilterGroup size="small" totalFiltersCount={totalFiltersCount} />
                        </UniversalFilters>
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
                        data-attr="filter-recordings-button"
                    >
                        Filters{' '}
                        {totalFiltersCount ? <LemonBadge.Number count={totalFiltersCount} size="small" /> : null}
                    </LemonButton>
                    <LemonModal
                        isOpen={isFiltersExpanded}
                        onClose={(): void => {
                            setIsFiltersExpanded(false)
                        }}
                        width={750}
                        footer={<ModalFooter />}
                    >
                        <>
                            <LemonTabs
                                activeKey={activeFilterTab}
                                onChange={(activeKey) => setActiveFilterTab(activeKey)}
                                size="small"
                                tabs={tabs}
                            />
                        </>
                    </LemonModal>
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

const RecordingsUniversalFilterGroup = ({
    size = 'small',
    totalFiltersCount,
    showAddFilter = true,
}: {
    size?: LemonButtonProps['size']
    totalFiltersCount?: number
    showAddFilter?: boolean
}): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)

    useEffect(() => {
        setAllowInitiallyOpen(true)
    }, [])

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <div className="w-full">
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            <div
                                className={
                                    showAddFilter
                                        ? 'flex flex-wrap items-center gap-2 border-t py-4'
                                        : 'flex flex-wrap gap-2 pt-2'
                                }
                            >
                                {(totalFiltersCount ?? 0) > 0 && showAddFilter && (
                                    <span className="font-semibold">Applied filters:</span>
                                )}
                                <RecordingsUniversalFilterGroup
                                    size={size}
                                    totalFiltersCount={totalFiltersCount}
                                    showAddFilter={showAddFilter}
                                />
                            </div>
                            {showAddFilter && (
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

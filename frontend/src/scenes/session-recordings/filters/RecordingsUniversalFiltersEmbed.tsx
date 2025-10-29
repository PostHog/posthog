import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconClock, IconEye, IconFilter, IconHide, IconPlus, IconRevert, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonInput, LemonModal, LemonTab, LemonTabs, Popover } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isCommentTextFilter, isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { MaxTool } from 'scenes/max/MaxTool'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFiltersGroup,
} from '~/types'

import { sessionRecordingSavedFiltersLogic } from '../filters/sessionRecordingSavedFiltersLogic'
import { TimestampFormat, playerSettingsLogic } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { createPlaylist, updatePlaylist } from '../playlist/playlistUtils'
import { defaultRecordingDurationFilter } from '../playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { CurrentFilterIndicator } from './CurrentFilterIndicator'
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

    return (
        <>
            <MaxTool
                identifier="search_session_recordings"
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
            <CurrentFilterIndicator />
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
    const [isSaveFiltersModalOpen, setIsSaveFiltersModalOpen] = useState(false)
    const [savedFilterName, setSavedFilterName] = useState('')

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

    const { savedFilters, appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)

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
                                <RecordingsUniversalFilterGroup />
                            </UniversalFilters>
                        </div>
                    </div>
                    <div className="flex justify-between gap-2 border-t pt-4 mx-2 mt-8 ">
                        <div className="flex flex-wrap gap-2 items-center justify-end">
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
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SessionRecording}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => setIsSaveFiltersModalOpen(true)}
                                        disabledReason={
                                            (totalFiltersCount ?? 0) === 0 ? 'No filters applied' : undefined
                                        }
                                        tooltip="Save filters for later"
                                    >
                                        Add to "Saved filters"
                                    </LemonButton>
                                </AccessControlAction>
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

const RecordingsUniversalFilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)
    const [isPopoverVisible, setIsPopoverVisible] = useState(false)
    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <RecordingsUniversalFilterGroup />

                        <Popover
                            overlay={
                                <UniversalFilters.PureTaxonomicFilter
                                    fullWidth={false}
                                    onChange={() => setIsPopoverVisible(false)}
                                />
                            }
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
                        operatorAllowlist={
                            isCommentTextFilter(filterOrGroup)
                                ? [PropertyOperator.IsSet, PropertyOperator.Exact, PropertyOperator.IContains]
                                : undefined
                        }
                    />
                )
            })}
        </>
    )
}

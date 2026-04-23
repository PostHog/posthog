import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    IconAsterisk,
    IconCheck,
    IconClock,
    IconEye,
    IconFilter,
    IconHide,
    IconPencil,
    IconPlus,
    IconRefresh,
    IconRevert,
    IconSearch,
    IconTrash,
    IconX,
} from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonTab,
    LemonTabs,
    LemonTag,
    Popover,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isCommentTextFilter, isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
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
    PropertyOperator,
    RecordingUniversalFilters,
    SessionRecordingPlaylistType,
    UniversalFiltersGroup,
} from '~/types'

import { sessionRecordingSavedFiltersLogic } from '../filters/sessionRecordingSavedFiltersLogic'
import { TimestampFormat, playerSettingsLogic } from '../player/playerSettingsLogic'
import { playlistFiltersLogic } from '../playlist/playlistFiltersLogic'
import { createPlaylist, stripSessionIds, updatePlaylist } from '../playlist/playlistUtils'
import {
    defaultRecordingDurationFilter,
    sessionRecordingsPlaylistLogic,
} from '../playlist/sessionRecordingsPlaylistLogic'
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
    currentSessionRecordingId,
    onReload,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    totalFiltersCount?: number
    currentSessionRecordingId?: string
    onReload?: () => void
}): JSX.Element => {
    const { sessionRecordingsResponseLoading } = useValues(sessionRecordingsPlaylistLogic)
    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)

    return (
        <>
            <div className="flex gap-2">
                <MaxTool
                    identifier="filter_session_recordings"
                    context={{
                        current_filters: filters,
                        current_session_id: currentSessionRecordingId,
                    }}
                    callback={(toolOutput: Record<string, any>) => {
                        // Improve type
                        setFilters(toolOutput.recordings_filters)
                        setIsFiltersExpanded(true)
                    }}
                    initialMaxPrompt="Show me recordings where "
                    suggestions={[
                        'Show recordings of people who visited signup in the last 24 hours',
                        'Show recordings showing user frustration',
                        'Show recordings of people who faced bugs',
                    ]}
                    onMaxOpen={() => setIsFiltersExpanded(false)}
                    className="grow"
                >
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
                    <CurrentFilterIndicator />
                </MaxTool>
                <LemonButton
                    type="secondary"
                    onClick={onReload}
                    icon={<IconRefresh />}
                    loading={sessionRecordingsResponseLoading}
                    size="small"
                    tooltip="Refresh list"
                    data-attr="refresh-recordings-list"
                />
            </div>
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

interface ReplayUniversalFiltersEmbedProps {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    className?: string
    allowReplayHogQLFilters?: boolean
    pinnedFilters?: UniversalFiltersGroup
}

export const RecordingsUniversalFiltersEmbed = ({ ...props }: ReplayUniversalFiltersEmbedProps): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const { activeFilterTab } = useValues(playlistFiltersLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistFiltersLogic)

    const { savedFilters } = useValues(sessionRecordingSavedFiltersLogic)

    const tabs: LemonTab<string>[] = [
        {
            key: 'filters',
            label: <div className="px-2">Filters</div>,
            content: <ReplayFiltersTab {...props} />,
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
            content: <SavedFilters setFilters={props.setFilters} />,
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

const RecordingsUniversalFilterGroup = ({
    hideAddFilterButton = false,
    pinnedFilters,
}: {
    hideAddFilterButton?: boolean
    pinnedFilters?: UniversalFiltersGroup
}): JSX.Element => {
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
                        <RecordingsUniversalFilterGroup
                            hideAddFilterButton={hideAddFilterButton}
                            pinnedFilters={pinnedFilters}
                        />

                        {!hideAddFilterButton && (
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
                                    data-attr="replay-filters-add-filter-button"
                                    icon={<IconPlus />}
                                    onClick={() => setIsPopoverVisible(!isPopoverVisible)}
                                >
                                    Add filter
                                </LemonButton>
                            </Popover>
                        )}
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={
                            pinnedFilters?.values.some((pv) => equal(pv, filterOrGroup))
                                ? undefined
                                : () => removeGroupValue(index)
                        }
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

const SaveFiltersModal = ({
    isOpen,
    setIsOpen,
    filters,
}: {
    isOpen: boolean
    setIsOpen: (o: boolean) => void
    filters: ReplayUniversalFiltersEmbedProps['filters']
}): JSX.Element => {
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)

    const [savedFilterName, setSavedFilterName] = useState('')

    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)

    const closeSaveFiltersModal = (): void => {
        setIsOpen(false)
        setSavedFilterName('')
    }

    const addSavedFilter = async (): Promise<void> => {
        const f = await createPlaylist(
            { name: savedFilterName, filters: stripSessionIds(filters), type: 'filters' },
            false
        )
        reportRecordingPlaylistCreated('new')
        loadSavedFilters()
        setIsOpen(false)
        setSavedFilterName('')
        setAppliedSavedFilter(f)
    }

    return (
        <LemonModal
            title="Save filters for later"
            description="You can access them on 'Saved filters' tab"
            isOpen={isOpen}
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

function SavedFilterNameEditor({
    appliedSavedFilter,
    hasFilterChanges,
    onClose,
    onRenamed,
}: {
    appliedSavedFilter: SessionRecordingPlaylistType
    hasFilterChanges: boolean
    onClose: () => void
    onRenamed: (updatedFilter: SessionRecordingPlaylistType) => void
}): JSX.Element {
    const [isRenaming, setIsRenaming] = useState(false)
    const [name, setName] = useState('')

    const doRename = async (): Promise<void> => {
        const trimmed = name.trim()
        if (!trimmed) {
            return
        }
        try {
            const f = await updatePlaylist(
                appliedSavedFilter.short_id,
                { name: trimmed, filters: appliedSavedFilter.filters },
                false
            )
            onRenamed(f)
            setIsRenaming(false)
        } catch {
            lemonToast.error('Failed to rename saved filter')
        }
    }

    if (isRenaming) {
        return (
            <div className="flex items-center gap-1 basis-full min-w-0">
                <LemonInput
                    value={name}
                    onChange={setName}
                    size="small"
                    autoFocus
                    fullWidth
                    onPressEnter={() => void doRename()}
                />
                <LemonButton size="xsmall" icon={<IconCheck />} onClick={() => void doRename()} tooltip="Save name" />
                <LemonButton size="xsmall" icon={<IconX />} onClick={() => setIsRenaming(false)} tooltip="Cancel" />
            </div>
        )
    }

    return (
        <>
            <LemonTag
                type={hasFilterChanges ? 'option' : 'primary'}
                icon={hasFilterChanges ? <IconAsterisk /> : undefined}
                closable
                onClose={onClose}
                className="min-w-0"
            >
                <span className="truncate">
                    {appliedSavedFilter.name || appliedSavedFilter.derived_name || 'Unnamed'}
                    {hasFilterChanges && ' (edited)'}
                </span>
            </LemonTag>
            <LemonButton
                size="xsmall"
                icon={<IconPencil />}
                onClick={() => {
                    setName(appliedSavedFilter.name || appliedSavedFilter.derived_name || '')
                    setIsRenaming(true)
                }}
                tooltip="Rename saved filter"
            />
        </>
    )
}

const ReplayFiltersTab = ({
    filters,
    setFilters,
    resetFilters,
    className,
    totalFiltersCount,
    allowReplayHogQLFilters = false,
    pinnedFilters,
}: ReplayUniversalFiltersEmbedProps): JSX.Element => {
    const [isSaveFiltersModalOpen, setIsSaveFiltersModalOpen] = useState(false)

    const [isPopoverVisible, setIsPopoverVisible] = useState(false)
    const [addFilterSearchQuery, setAddFilterSearchQuery] = useState('')

    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const durationFilter = filters.duration?.[0] ?? defaultRecordingDurationFilter

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.Replay,
        TaxonomicFilterGroupType.ReplaySavedFilters,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...groupsTaxonomicTypes,
        ...(hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
        ...(hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
        TaxonomicFilterGroupType.EmailAddresses,
        TaxonomicFilterGroupType.AutocaptureEvents,
    ]

    if (allowReplayHogQLFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.HogQLExpression)
    }

    taxonomicGroupTypes.unshift(TaxonomicFilterGroupType.SuggestedFilters)

    const { appliedSavedFilter, pendingFilterApplication } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters, setAppliedSavedFilter, clearPendingFilterApplication } = useActions(
        sessionRecordingSavedFiltersLogic
    )
    const { setActiveFilterTab } = useActions(playlistFiltersLogic)

    useEffect(() => {
        if (!pendingFilterApplication) {
            return
        }

        if (pendingFilterApplication.filters) {
            setFilters(stripSessionIds(pendingFilterApplication.filters as Partial<RecordingUniversalFilters>))
            setAppliedSavedFilter(pendingFilterApplication)
            setActiveFilterTab('filters')
        }

        clearPendingFilterApplication()
    }, [pendingFilterApplication, setFilters, setActiveFilterTab, setAppliedSavedFilter, clearPendingFilterApplication])

    const updateSavedFilter = async (): Promise<void> => {
        if (appliedSavedFilter === null) {
            return
        }

        const f = await updatePlaylist(
            appliedSavedFilter.short_id,
            { filters: stripSessionIds(filters), type: 'filters' },
            false
        )
        loadSavedFilters()
        setAppliedSavedFilter(f)
    }

    const handleResetFilters = (): void => {
        resetFilters?.()
        setAppliedSavedFilter(null)
    }

    const hasFilterChanges = appliedSavedFilter ? !equal(appliedSavedFilter.filters, filters) : false

    return (
        <div className={clsx('relative bg-surface-primary w-full h-full', className)}>
            {appliedSavedFilter && (
                <div className="border-b px-2 py-3 flex flex-wrap items-center gap-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1 basis-3/5">
                        <span className="font-medium whitespace-nowrap shrink-0">Loaded saved filter:</span>
                        <SavedFilterNameEditor
                            appliedSavedFilter={appliedSavedFilter}
                            hasFilterChanges={hasFilterChanges}
                            onClose={() => {
                                resetFilters?.()
                                setAppliedSavedFilter(null)
                            }}
                            onRenamed={(updatedFilter) => {
                                loadSavedFilters()
                                setAppliedSavedFilter(updatedFilter)
                            }}
                        />
                    </div>
                    {hasFilterChanges && (
                        <div className="flex gap-2 ml-auto shrink-0">
                            <LemonButton
                                data-attr="replay-filters-discard-changes-button"
                                type="secondary"
                                size="small"
                                icon={<IconTrash />}
                                onClick={() =>
                                    setFilters(
                                        stripSessionIds(
                                            appliedSavedFilter.filters as Partial<RecordingUniversalFilters>
                                        )
                                    )
                                }
                            >
                                Discard changes
                            </LemonButton>
                            <LemonButton
                                data-attr="replay-filters-save-changes-button"
                                type="secondary"
                                status="danger"
                                size="small"
                                className="max-w-xs"
                                truncate
                                onClick={() => void updateSavedFilter()}
                            >
                                Save changes to "{appliedSavedFilter.name || 'Unnamed'}"
                            </LemonButton>
                        </div>
                    )}
                </div>
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

            <UniversalFilters
                rootKey="session-recordings"
                group={filters.filter_group}
                taxonomicGroupTypes={taxonomicGroupTypes}
                onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
            >
                <div className="px-2 mt-2 min-w-0">
                    {/* Add filter search input scoped to the first nested group */}
                    {filters.filter_group.values.length > 0 &&
                        isUniversalGroupFilterLike(filters.filter_group.values[0]) && (
                            <UniversalFilters
                                rootKey="session-recordings.nested"
                                group={filters.filter_group.values[0]}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                onChange={(nestedGroup) => {
                                    const newFilterGroup = {
                                        ...filters.filter_group,
                                        values: [nestedGroup, ...filters.filter_group.values.slice(1)],
                                    }
                                    setFilters({ filter_group: newFilterGroup })
                                }}
                            >
                                <Popover
                                    overlay={
                                        <UniversalFilters.PureTaxonomicFilter
                                            fullWidth={false}
                                            onChange={() => {
                                                setIsPopoverVisible(false)
                                                setAddFilterSearchQuery('')
                                            }}
                                            searchQuery={addFilterSearchQuery}
                                            hideSearchInput
                                        />
                                    }
                                    placement="bottom-start"
                                    visible={isPopoverVisible}
                                    onClickOutside={() => {
                                        setIsPopoverVisible(false)
                                        setAddFilterSearchQuery('')
                                    }}
                                >
                                    <div className="w-full max-w-[600px] shrink grow-0">
                                        <LemonInput
                                            type="search"
                                            size="small"
                                            fullWidth
                                            data-attr="replay-filters-add-filter-input"
                                            prefix={<IconSearch />}
                                            placeholder="Search suggested filters, URLs, email addresses, recent, pinned..."
                                            value={addFilterSearchQuery}
                                            onChange={(value) => {
                                                setAddFilterSearchQuery(value)
                                                if (!isPopoverVisible) {
                                                    setIsPopoverVisible(true)
                                                }
                                            }}
                                            onFocus={() => setIsPopoverVisible(true)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Escape') {
                                                    setIsPopoverVisible(false)
                                                    setAddFilterSearchQuery('')
                                                    e.preventDefault()
                                                }
                                            }}
                                        />
                                    </div>
                                </Popover>
                            </UniversalFilters>
                        )}
                </div>

                <div className="flex justify-between flex-wrap gap-2 px-2 mt-4">
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
                                { key: 'All time', values: ['-5y'] },
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
                        <RecordingsUniversalFilterGroup hideAddFilterButton={true} pinnedFilters={pinnedFilters} />
                    </div>
                </div>
            </UniversalFilters>

            <LemonDivider className="mt-4" />

            <div className="flex items-center py-2 justify-between px-1 gap-2">
                {useFeatureFlag('SHOW_REPLAY_FILTERS_FEEDBACK_BUTTON') && (
                    <LemonButton
                        id="replay-filters-feedback-button"
                        type="tertiary"
                        status="danger"
                        size="small"
                        data-attr="replay-filters-feedback-button"
                    >
                        Unexpected filter results?
                    </LemonButton>
                )}
                <div className="flex gap-2 ml-auto">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={handleResetFilters}
                        icon={<IconRevert />}
                        tooltip="Remove all filters and reset to defaults"
                        disabledReason={
                            !(resetFilters && (totalFiltersCount ?? 0) > 0) ? 'No filters applied' : undefined
                        }
                    >
                        Reset filters
                    </LemonButton>
                    <LemonButton type="primary" size="small" onClick={() => setIsSaveFiltersModalOpen(true)}>
                        Save as new filter
                    </LemonButton>
                </div>
            </div>

            <SaveFiltersModal isOpen={isSaveFiltersModalOpen} setIsOpen={setIsSaveFiltersModalOpen} filters={filters} />
        </div>
    )
}

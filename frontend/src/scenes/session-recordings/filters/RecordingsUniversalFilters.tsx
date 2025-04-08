import { IconClock, IconEye, IconFilter, IconHide, IconRevert } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonButtonProps, LemonModal, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { MaxTool } from 'scenes/max/MaxTool'
import { SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, ReplayTabs, UniversalFiltersGroup } from '~/types'

import { playerSettingsLogic, TimestampFormat } from '../player/playerSettingsLogic'
import { playlistLogic } from '../playlist/playlistLogic'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { DurationFilter } from './DurationFilter'
import { PeopleFilter } from './PeopleFilter'
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

export const RecordingsUniversalFilters = ({
    filters,
    setFilters,
    resetFilters,
    totalFiltersCount,
    className,
    allowReplayHogQLFilters = false,
    allowReplayFlagsFilters = false,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters?: () => void
    totalFiltersCount?: number
    className?: string
    allowReplayFlagsFilters?: boolean
    allowReplayHogQLFilters?: boolean
}): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

    const durationFilter = filters.duration[0]

    const { isFiltersExpanded, activeFilterTab } = useValues(playlistLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistLogic)
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)

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

    if (allowReplayFlagsFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.EventFeatureFlags)
    }

    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    const { savedFilters } = useValues(savedFiltersLogic)

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
                onMaxOpen={() => setIsFiltersExpanded(true)}
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
                        Filters{' '}
                        {totalFiltersCount && totalFiltersCount > 0 ? (
                            <LemonBadge.Number count={totalFiltersCount} />
                        ) : null}
                    </LemonButton>
                    <LemonModal
                        isOpen={isFiltersExpanded}
                        onClose={() => setIsFiltersExpanded(false)}
                        width={750}
                        footer={
                            <div className="flex justify-between p-2 gap-2">
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    onClick={resetFilters}
                                    icon={<IconRevert />}
                                    tooltip="Reset any changes you've made to the filters"
                                    disabledReason={
                                        !(resetFilters && (totalFiltersCount ?? 0) > 0)
                                            ? 'No filters applied'
                                            : undefined
                                    }
                                >
                                    Reset filters
                                </LemonButton>
                                {(totalFiltersCount ?? 0) > 0 &&
                                    !savedFilters.results?.find((filter) => equal(filter.filters, filters)) && (
                                        <LemonButton type="primary" size="xsmall" onClick={() => {}}>
                                            Save filters
                                        </LemonButton>
                                    )}
                                <LemonButton type="primary" size="small" onClick={() => setIsFiltersExpanded(false)}>
                                    Close
                                </LemonButton>
                            </div>
                        }
                    >
                        <>
                            <LemonTabs
                                activeKey={activeFilterTab}
                                onChange={(activeKey) => setActiveFilterTab(activeKey)}
                                size="small"
                                tabs={[
                                    {
                                        key: 'filters',
                                        label: <div className="px-2">Filters</div>,
                                        content: (
                                            <div
                                                className={clsx(
                                                    'relative divide-y bg-surface-primary w-full ',
                                                    className
                                                )}
                                            >
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
                                                        size="xsmall"
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
                                                            size="xsmall"
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
                                                            size="xsmall"
                                                        />
                                                    </div>
                                                    <div>
                                                        <TestAccountFilter
                                                            size="xsmall"
                                                            filters={filters}
                                                            onChange={(testFilters) =>
                                                                setFilters({
                                                                    filter_test_accounts:
                                                                        testFilters.filter_test_accounts,
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
                                                        onChange={(filterGroup) =>
                                                            setFilters({ filter_group: filterGroup })
                                                        }
                                                    >
                                                        <RecordingsUniversalFilterGroup size="xsmall" />
                                                    </UniversalFilters>
                                                </div>
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'saved',
                                        label: (
                                            <div className="px-2 flex">
                                                {' '}
                                                {savedFilters.results?.length ? (
                                                    <LemonBadge.Number
                                                        count={savedFilters.results?.length}
                                                        className="mr-2"
                                                    />
                                                ) : null}{' '}
                                                Saved filters
                                            </div>
                                        ),
                                        content: <SavedFilters setFilters={setFilters} />,
                                    },
                                    {
                                        key: 'person',
                                        label: <div className="px-2">Person</div>,
                                        content: <PeopleFilter setFilters={setFilters} />,
                                    },
                                ]}
                            />
                        </>
                    </LemonModal>
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

const RecordingsUniversalFilterGroup = ({ size = 'small' }: { size?: LemonButtonProps['size'] }): JSX.Element => {
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
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <RecordingsUniversalFilterGroup size={size} />
                        <UniversalFilters.AddFilterButton size={size} type="secondary" />
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

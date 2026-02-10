import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { DurationType } from '~/types'

import { DurationFilter } from '../filters/DurationFilter'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from '../playlist/sessionRecordingsPlaylistLogic'

export function InlineFilterBar({ logicKey }: SessionRecordingPlaylistLogicProps): JSX.Element {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    useMountedLogic(groupsModel)

    const logic = sessionRecordingsPlaylistLogic({ logicKey })
    const { filters } = useValues(logic)
    const { setFilters } = useActions(logic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const [isAddFilterPopoverOpen, setIsAddFilterPopoverOpen] = useState(false)

    const durationFilter = filters.duration[0]
    const durationType = durationFilter.key as DurationType

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.Replay,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...groupsTaxonomicTypes,
    ]

    // Get the nested filter group for the taxonomic filter
    const nestedGroup =
        filters.filter_group.values.length > 0 && isUniversalGroupFilterLike(filters.filter_group.values[0])
            ? filters.filter_group.values[0]
            : undefined

    return (
        <div className="flex gap-2 items-start justify-between p-3 bg-surface-primary border-b border-border-primary">
            <div className="flex gap-2 items-center flex-wrap">
                <DateFilter
                    dateFrom={filters.date_from ?? '-3d'}
                    dateTo={filters.date_to ?? null}
                    onChange={(changedDateFrom, changedDateTo) =>
                        setFilters({
                            date_from: changedDateFrom,
                            date_to: changedDateTo,
                        })
                    }
                    dateOptions={[
                        { key: 'Custom', values: [] },
                        { key: 'Last 24 hours', values: ['-24h'] },
                        { key: 'Last 3 days', values: ['-3d'] },
                        { key: 'Last 7 days', values: ['-7d'] },
                        { key: 'Last 30 days', values: ['-30d'] },
                        { key: 'All time', values: ['-90d'] },
                    ]}
                    size="small"
                    type="secondary"
                />

                <DurationFilter
                    pageKey={logicKey ?? 'inline-filter-bar'}
                    recordingDurationFilter={durationFilter}
                    durationTypeFilter={durationType}
                    onChange={(newFilter, newDurationType) => {
                        setFilters({ duration: [{ ...newFilter, key: newDurationType }] })
                    }}
                    size="small"
                    type="secondary"
                />

                {nestedGroup && (
                    <UniversalFilters
                        rootKey="inline-filter-bar"
                        group={nestedGroup}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(updatedGroup) => {
                            setFilters({
                                filter_group: {
                                    ...filters.filter_group,
                                    values: [updatedGroup],
                                },
                            })
                        }}
                    >
                        <InlineFilterChips />
                        <Popover
                            visible={isAddFilterPopoverOpen}
                            onClickOutside={() => setIsAddFilterPopoverOpen(false)}
                            overlay={
                                <UniversalFilters.PureTaxonomicFilter
                                    fullWidth={false}
                                    onChange={() => {
                                        setIsAddFilterPopoverOpen(false)
                                    }}
                                />
                            }
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={() => setIsAddFilterPopoverOpen(!isAddFilterPopoverOpen)}
                                data-attr="add-filter-button"
                            >
                                Filter
                            </LemonButton>
                        </Popover>
                    </UniversalFilters>
                )}
            </div>

            <div className="flex-shrink-0 min-w-64">
                <TestAccountFilterSwitch
                    checked={!!filters.filter_test_accounts}
                    onChange={(checked) => setFilters({ filter_test_accounts: checked })}
                />
            </div>
        </div>
    )
}

function InlineFilterChips(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { removeGroupValue, replaceGroupValue } = useActions(universalFiltersLogic)

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <InlineFilterChips />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        metadataSource={{ kind: NodeKind.RecordingsQuery }}
                    />
                )
            })}
        </>
    )
}

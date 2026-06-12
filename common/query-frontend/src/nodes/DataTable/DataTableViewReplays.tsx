import { useValues } from 'kea'

import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { dataTableLogic } from './dataTableLogic'

export function DataTableViewReplays(): JSX.Element | null {
    const { context } = useValues(dataTableLogic)
    const cohortId = context?.cohortId

    if (!cohortId) {
        return null
    }

    const filters: Partial<RecordingUniversalFilters> = {
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Cohort,
                            key: 'id',
                            operator: PropertyOperator.In,
                            value: cohortId,
                        },
                    ],
                },
            ],
        },
    }

    return (
        <ViewRecordingsPlaylistButton
            filters={filters}
            type="secondary"
            label="View session recordings"
            data-attr="view-replays-from-cohort-button"
        />
    )
}

import { useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
} from '~/types'

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
        <LemonButton
            type="secondary"
            icon={<IconRewindPlay />}
            to={urls.replay(ReplayTabs.Home, filters)}
            data-attr="view-replays-from-cohort-button"
        >
            View session recordings
        </LemonButton>
    )
}

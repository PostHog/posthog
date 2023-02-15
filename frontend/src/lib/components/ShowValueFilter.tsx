import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFunnelsFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'
import { TrendsFilterType } from '~/types'

export function ShowValuesFilter(): JSX.Element | null {
    const { filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)

    const checked =
        (filters && isTrendsFilter(filters)) || isFunnelsFilter(filters) ? filters.show_values_on_series : false

    return (
        <LemonCheckbox
            onChange={(checked) => {
                // as trends filter just to make typescript happy
                setFilters({ ...filters, show_values_on_series: checked } as TrendsFilterType)
            }}
            checked={checked}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}

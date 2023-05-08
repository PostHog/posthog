import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType, FilterType, InsightType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    return (
        <TaxonomicBreakdownFilterComponent
            breakdownFilter={filters}
            isTrends={filters.insight === InsightType.TRENDS}
            updateBreakdown={(breakdownFilter) => setFilters?.(breakdownFilter, true)}
            updateDisplay={(display) => setFilters?.({ display } as TrendsFilterType, true)}
        />
    )
}

export interface TaxonomicBreakdownFilterComponentProps {
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown?: (breakdown: BreakdownFilter) => void
    updateDisplay?: (display: ChartDisplayType) => void
}

export function TaxonomicBreakdownFilterComponent({
    breakdownFilter,
    display,
    isTrends,
    updateBreakdown,
    updateDisplay,
}: TaxonomicBreakdownFilterComponentProps): JSX.Element {
    const logicProps = {
        breakdownFilter: breakdownFilter || {},
        display,
        updateBreakdown: updateBreakdown || null,
        updateDisplay,
        isTrends,
    }
    const { hasBreakdown, hasNonCohortBreakdown, breakdownArray, isViewOnly } = useValues(
        taxonomicBreakdownFilterLogic(logicProps)
    )

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown) => <BreakdownTag key={breakdown} breakdown={breakdown} />)

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {!isViewOnly && !hasNonCohortBreakdown ? <TaxonomicBreakdownButton /> : null}
            </div>
        </BindLogic>
    )
}

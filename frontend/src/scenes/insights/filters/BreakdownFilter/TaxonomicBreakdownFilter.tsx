import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType, FilterType, InsightType, PropertyFilterType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic, TaxonomicBreakdownFilterLogicProps } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    return (
        <TaxonomicBreakdownFilterComponent
            breakdownFilter={filters}
            display={(filters as TrendsFilterType).display}
            isTrends={filters.insight === InsightType.TRENDS}
            updateBreakdown={setFilters ? (breakdownFilter) => setFilters(breakdownFilter, true) : undefined}
            updateDisplay={setFilters ? (display) => setFilters({ display } as TrendsFilterType, true) : undefined}
        />
    )
}

export interface TaxonomicBreakdownFilterComponentProps {
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown?: (breakdown: BreakdownFilter) => void
    updateDisplay?: (display: ChartDisplayType | undefined) => void
    isDataExploration?: boolean
}

export function TaxonomicBreakdownFilterComponent({
    breakdownFilter,
    display,
    isTrends,
    updateBreakdown,
    updateDisplay,
    isDataExploration = false,
}: TaxonomicBreakdownFilterComponentProps): JSX.Element {
    const logicProps: TaxonomicBreakdownFilterLogicProps = {
        isTrends,
        display,
        breakdownFilter: breakdownFilter || {},
        updateBreakdown: updateBreakdown || null,
        updateDisplay: updateDisplay || null,
        isDataExploration,
    }
    const { hasBreakdown, hasNonCohortBreakdown, breakdownArray, isViewOnly } = useValues(
        taxonomicBreakdownFilterLogic(logicProps)
    )

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown) => (
              <BreakdownTag
                  key={breakdown}
                  breakdown={breakdown}
                  breakdownType={
                      (breakdownFilter?.breakdown_type as PropertyFilterType | undefined) ?? PropertyFilterType.Event
                  }
                  isTrends={isTrends}
              />
          ))

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {!isViewOnly && !hasNonCohortBreakdown ? <TaxonomicBreakdownButton /> : null}
            </div>
        </BindLogic>
    )
}

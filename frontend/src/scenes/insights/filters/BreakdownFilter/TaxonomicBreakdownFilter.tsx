import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { FilterType, InsightType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const logicProps = { filters, setFilters }
    const { hasBreakdown, hasNonCohortBreakdown, breakdownArray, isViewOnly } = useValues(
        taxonomicBreakdownFilterLogic(logicProps)
    )

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown) => <BreakdownTag key={breakdown} breakdown={breakdown} filters={filters} />)

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {!isViewOnly && !hasNonCohortBreakdown ? (
                    <TaxonomicBreakdownButton
                        includeSessions={filters.insight === InsightType.TRENDS} // TODO: convert to data exploration
                    />
                ) : null}
            </div>
        </BindLogic>
    )
}

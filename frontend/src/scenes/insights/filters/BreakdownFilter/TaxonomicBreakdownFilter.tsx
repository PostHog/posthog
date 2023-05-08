import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FilterType, InsightType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)

    const logicProps = { filters, setFilters, getPropertyDefinition }
    const { hasBreakdown, hasNonCohortBreakdown, breakdownArray } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown) => (
              <BreakdownTag key={breakdown} breakdown={breakdown} filters={filters} setFilters={setFilters} />
          ))

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {setFilters && !hasNonCohortBreakdown ? (
                    <TaxonomicBreakdownButton
                        includeSessions={filters.insight === InsightType.TRENDS} // TODO: convert to data exploration
                    />
                ) : null}
            </div>
        </BindLogic>
    )
}

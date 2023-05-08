import { BindLogic, useActions, useValues } from 'kea'
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
    const { hasBreakdown, hasNonCohortBreakdown, taxonomicBreakdownType, breakdownArray } = useValues(
        taxonomicBreakdownFilterLogic(logicProps)
    )
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic(logicProps))

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown, index) => (
              <BreakdownTag
                  key={`${breakdown}-${index}`}
                  logicKey={`${breakdown}-${index}`}
                  breakdown={breakdown}
                  filters={filters}
                  setFilters={setFilters}
              />
          ))

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {setFilters && !hasNonCohortBreakdown ? (
                    <TaxonomicBreakdownButton
                        breakdownType={taxonomicBreakdownType}
                        addBreakdown={addBreakdown}
                        includeSessions={filters.insight === InsightType.TRENDS} // TODO: convert to data exploration
                    />
                ) : null}
            </div>
        </BindLogic>
    )
}

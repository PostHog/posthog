import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType } from '~/types'
import { BreakdownTag, BreakdownTagComponent } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic, TaxonomicBreakdownFilterLogicProps } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown?: (breakdown: BreakdownFilter) => void
    updateDisplay?: (display: ChartDisplayType | undefined) => void
}

export function TaxonomicBreakdownFilter({
    breakdownFilter,
    display,
    isTrends,
    updateBreakdown,
    updateDisplay,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const logicProps: TaxonomicBreakdownFilterLogicProps = {
        isTrends,
        display,
        breakdownFilter: breakdownFilter || {},
        updateBreakdown: updateBreakdown || null,
        updateDisplay: updateDisplay || null,
    }
    const { hasBreakdown, hasNonCohortBreakdown, breakdownArray } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    const isViewOnly = !updateBreakdown
    const BreakdownComponent = isViewOnly ? BreakdownTagComponent : BreakdownTag

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown) => (
              <BreakdownComponent
                  key={breakdown}
                  breakdown={breakdown}
                  breakdownType={breakdownFilter?.breakdown_type ?? 'event'}
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

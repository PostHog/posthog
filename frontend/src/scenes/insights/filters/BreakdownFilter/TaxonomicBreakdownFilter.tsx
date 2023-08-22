import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType, InsightLogicProps, PropertyFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { taxonomicBreakdownFilterLogic, TaxonomicBreakdownFilterLogicProps } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    insightProps: InsightLogicProps
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown?: (breakdown: BreakdownFilter) => void
    updateDisplay?: (display: ChartDisplayType | undefined) => void
}

export function TaxonomicBreakdownFilter({
    insightProps,
    breakdownFilter,
    display,
    isTrends,
    updateBreakdown,
    updateDisplay,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const logicProps: TaxonomicBreakdownFilterLogicProps = {
        insightProps,
        isTrends,
        display,
        breakdownFilter: breakdownFilter || {},
        updateBreakdown: updateBreakdown || null,
        updateDisplay: updateDisplay || null,
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

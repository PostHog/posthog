import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'

import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { EditableBreakdownTag } from './BreakdownTag'
import { taxonomicBreakdownFilterLogic, TaxonomicBreakdownFilterLogicProps } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    insightProps: InsightLogicProps
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
}

export function TaxonomicBreakdownFilter({
    insightProps,
    breakdownFilter,
    display,
    isTrends,
    updateBreakdownFilter,
    updateDisplay,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const logicProps: TaxonomicBreakdownFilterLogicProps = {
        insightProps,
        isTrends,
        display,
        breakdownFilter: breakdownFilter || {},
        updateBreakdownFilter,
        updateDisplay,
    }
    const { breakdownArray, hasNonCohortBreakdown } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    const tags = breakdownArray.map((breakdown) => (
        <EditableBreakdownTag
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
                {!hasNonCohortBreakdown && <TaxonomicBreakdownButton />}
            </div>
        </BindLogic>
    )
}

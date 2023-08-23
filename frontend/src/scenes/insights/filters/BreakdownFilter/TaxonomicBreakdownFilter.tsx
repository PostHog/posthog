import { BindLogic, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import { taxonomicBreakdownFilterLogic, TaxonomicBreakdownFilterLogicProps } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown: (breakdown: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
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
        updateBreakdown,
        updateDisplay,
    }
    const { breakdownArray, hasNonCohortBreakdown } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    const tags = breakdownArray.map((breakdown) => (
        <BreakdownTag
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

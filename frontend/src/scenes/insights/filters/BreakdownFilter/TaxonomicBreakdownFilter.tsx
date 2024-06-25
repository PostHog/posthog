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
    disabledReason?: string
    updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
}

export function TaxonomicBreakdownFilter({
    insightProps,
    breakdownFilter,
    display,
    isTrends,
    disabledReason,
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
    const { breakdownArray, maxBreakdownsSelected } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    const tags = breakdownArray.map((breakdown) =>
        typeof breakdown === 'object' ? (
            <EditableBreakdownTag
                key={breakdown.property}
                breakdown={breakdown.property}
                breakdownType={breakdown.type ?? 'event'}
                isTrends={isTrends}
            />
        ) : (
            <EditableBreakdownTag
                key={breakdown}
                breakdown={breakdown}
                breakdownType={breakdownFilter?.breakdown_type ?? 'event'}
                isTrends={isTrends}
            />
        )
    )

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {!maxBreakdownsSelected && <TaxonomicBreakdownButton disabledReason={disabledReason} />}
            </div>
        </BindLogic>
    )
}

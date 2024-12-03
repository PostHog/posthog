import { IconGear } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from '~/lib/lemon-ui/LemonButton'
import { LemonLabel } from '~/lib/lemon-ui/LemonLabel'
import { Popover } from '~/lib/lemon-ui/Popover'
import { BreakdownFilter } from '~/queries/schema'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { EditableBreakdownTag } from './BreakdownTag'
import { GlobalBreakdownOptionsMenu } from './GlobalBreakdownOptionsMenu'
import { TaxonomicBreakdownButton } from './TaxonomicBreakdownButton'
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
    const { breakdownArray, isAddBreakdownDisabled, breakdownOptionsOpened, isMultipleBreakdownsEnabled } = useValues(
        taxonomicBreakdownFilterLogic(logicProps)
    )
    const { toggleBreakdownOptions } = useActions(taxonomicBreakdownFilterLogic(logicProps))

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
            <div className="flex items-center justify-between gap-2">
                <LemonLabel info="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited.">
                    Breakdown by
                </LemonLabel>
                {isMultipleBreakdownsEnabled && (
                    <Popover
                        overlay={<GlobalBreakdownOptionsMenu />}
                        visible={breakdownOptionsOpened}
                        onClickOutside={() => toggleBreakdownOptions(false)}
                    >
                        <LemonButton
                            icon={<IconGear />}
                            size="small"
                            noPadding
                            onClick={() => toggleBreakdownOptions(!breakdownOptionsOpened)}
                        />
                    </Popover>
                )}
            </div>
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                {!isAddBreakdownDisabled && <TaxonomicBreakdownButton disabledReason={disabledReason} />}
            </div>
        </BindLogic>
    )
}

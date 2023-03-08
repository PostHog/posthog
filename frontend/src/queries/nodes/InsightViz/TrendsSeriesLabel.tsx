import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { QueryEditorFilterProps } from '~/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonButton } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { isTrendsQuery } from '~/queries/utils'
import { getDisplay } from './utils'

export function TrendsSeriesLabel({ query, insightProps }: QueryEditorFilterProps): JSX.Element {
    const { isFormulaOn } = useValues(trendsLogic(insightProps))
    const { setIsFormulaOn } = useActions(trendsLogic(insightProps))

    const display = getDisplay(query)
    const formulaModeButtonDisabled: boolean =
        isFormulaOn &&
        isTrendsQuery(query) &&
        !!display &&
        SINGLE_SERIES_DISPLAY_TYPES.includes(display) &&
        query.series.length > 1

    return (
        <div className="flex items-center justify-between w-full">
            <span>{isFormulaOn ? 'Variables' : 'Series'}</span>
            <Tooltip
                title={
                    formulaModeButtonDisabled
                        ? 'This chart type does not support multiple series, so in order to disable formula mode, remove variables or switch to a different chart type.'
                        : 'Make your own formula the output of the insight with formula mode. Use graph series as variables.'
                }
            >
                {/** The negative margin negates the button's effect on label sizing. */}
                <div className="-my-1">
                    <LemonButton
                        size="small"
                        onClick={() => setIsFormulaOn(!isFormulaOn)}
                        disabled={formulaModeButtonDisabled}
                        icon={<IconCalculate />}
                        id="trends-formula-switch"
                    >
                        {isFormulaOn ? 'Disable' : 'Enable'} formula mode
                    </LemonButton>
                </div>
            </Tooltip>
        </div>
    )
}

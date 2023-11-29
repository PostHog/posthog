import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function TrendsSeriesLabel({ insightProps }: EditorFilterProps): JSX.Element {
    const { hasFormula, isTrends, display, series } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const canDisableFormula: boolean =
        !isTrends || !display || !SINGLE_SERIES_DISPLAY_TYPES.includes(display) || series?.length === 1

    const formulaModeButtonDisabled = hasFormula && !canDisableFormula

    return (
        <div className="flex items-center justify-between w-full">
            <span>{hasFormula ? 'Variables' : 'Series'}</span>
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
                        onClick={() => updateInsightFilter({ formula: hasFormula ? undefined : '' })}
                        disabled={formulaModeButtonDisabled}
                        icon={<IconCalculate />}
                        id="trends-formula-switch"
                    >
                        {hasFormula ? 'Disable' : 'Enable'} formula mode
                    </LemonButton>
                </div>
            </Tooltip>
        </div>
    )
}

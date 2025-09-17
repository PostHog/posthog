import { useActions, useValues } from 'kea'

import { IconCalculator } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { SINGLE_SERIES_DISPLAY_TYPES } from '~/lib/constants'
import { EditorFilterProps } from '~/types'

export function TrendsSeriesLabel({ insightProps }: EditorFilterProps): JSX.Element {
    const { hasFormula, isTrends, display, series } = useValues(insightVizDataLogic(insightProps))
    const { toggleFormulaMode } = useActions(insightVizDataLogic(insightProps))

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
                        : 'Make your own formula(s) the output of the insight with formula mode. Use graph series as variables.'
                }
            >
                <div className="-my-1">
                    <LemonButton
                        size="small"
                        onClick={() => toggleFormulaMode()}
                        disabled={formulaModeButtonDisabled}
                        icon={<IconCalculator />}
                        id="trends-formula-switch"
                    >
                        {hasFormula ? 'Disable' : 'Enable'} formula mode
                    </LemonButton>
                </div>
            </Tooltip>
        </div>
    )
}

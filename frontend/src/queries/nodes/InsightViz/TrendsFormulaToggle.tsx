import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { SINGLE_SERIES_DISPLAY_TYPES } from '~/lib/constants'
import { EditorFilterProps } from '~/types'

export function TrendsFormulaToggle({ insightProps }: EditorFilterProps): JSX.Element {
    const { hasFormula, isTrends, display, series } = useValues(insightVizDataLogic(insightProps))
    const { toggleFormulaMode } = useActions(insightVizDataLogic(insightProps))

    const canDisableFormula: boolean =
        !isTrends || !display || !SINGLE_SERIES_DISPLAY_TYPES.includes(display) || series?.length === 1

    const formulaModeButtonDisabled = hasFormula && !canDisableFormula

    return (
        <Tooltip
            title={
                formulaModeButtonDisabled
                    ? 'This chart type does not support multiple series, so in order to disable formula mode, remove variables or switch to a different chart type.'
                    : 'Use graph series as variables in custom formulas'
            }
        >
            <span>
                <LemonSwitch
                    checked={hasFormula}
                    onChange={() => toggleFormulaMode()}
                    disabled={formulaModeButtonDisabled}
                    label="Formula"
                    size="small"
                    bordered
                />
            </span>
        </Tooltip>
    )
}

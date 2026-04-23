import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput } from '@posthog/lemon-ui'

import { DEFAULT_DECIMAL_PLACES } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function DecimalPlacesEditorFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const reportChange = useDebouncedCallback(() => {
        posthog.capture('decimal places changed', { decimal_places: trendsFilter?.decimalPlaces })
    }, 500)

    return (
        <div className="px-2 pb-2">
            <LemonInput
                type="number"
                size="small"
                step={1}
                min={0}
                max={9}
                defaultValue={DEFAULT_DECIMAL_PLACES}
                value={trendsFilter?.decimalPlaces}
                onChange={(value) => {
                    updateInsightFilter({ decimalPlaces: value })
                    reportChange()
                }}
                fullWidth
            />
        </div>
    )
}

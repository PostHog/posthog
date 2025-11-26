import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowAlertForecastIntervalsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertForecastIntervals } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertForecastIntervals = (): void => {
        updateInsightFilter({ showAlertForecastIntervals: !showAlertForecastIntervals })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowAlertForecastIntervals}
            checked={!!showAlertForecastIntervals}
            label={<span className="font-normal">Show alert forecast intervals</span>}
            size="small"
        />
    )
}

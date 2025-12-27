import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowAlertPointsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertPoints } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertPoints = (): void => {
        updateInsightFilter({ showAlertPoints: !showAlertPoints })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowAlertPoints}
            checked={!!showAlertPoints}
            label={<span className="font-normal">Show alert points</span>}
            size="small"
        />
    )
}

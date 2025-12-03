import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowAlertBreachPointsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertBreachPoints } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertBreachPoints = (): void => {
        updateInsightFilter({ showAlertBreachPoints: !showAlertBreachPoints })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowAlertBreachPoints}
            checked={!!showAlertBreachPoints}
            label={<span className="font-normal">Highlight alert breach points</span>}
            size="small"
        />
    )
}

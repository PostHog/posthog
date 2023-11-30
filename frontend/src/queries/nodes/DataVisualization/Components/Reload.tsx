import { useActions, useMountedLogic, useValues } from 'kea'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export function Reload(): JSX.Element {
    const logic = useMountedLogic(dataVisualizationLogic)
    const { responseLoading } = useValues(logic)
    const { loadData, cancelQuery } = useActions(logic)

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    loadData()
                }
            }}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}

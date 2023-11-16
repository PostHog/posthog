import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'

export function Reload(): JSX.Element {
    const { responseLoading } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)

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

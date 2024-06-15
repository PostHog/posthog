import { useActions, useValues } from 'kea'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

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
                    loadData(true)
                }
            }}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}

export function ReloadAll(): JSX.Element {
    const { areAnyLoading } = useValues(dataNodeCollectionLogic)
    const { reloadAll } = useActions(dataNodeCollectionLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => {
                reloadAll()
            }}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={areAnyLoading ? <Spinner textColored /> : <IconRefresh />}
            disabledReason={areAnyLoading ? 'Loading' : undefined}
        >
            Reload
        </LemonButton>
    )
}

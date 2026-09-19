import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

export function Reload(): JSX.Element {
    const { response, responseLoading, query } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)

    // Cancelling the first load leaves an empty state, so the cancel is only offered once there are
    // results to return to.
    const canCancel = responseLoading && !!response

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                if (canCancel) {
                    cancelQuery()
                } else {
                    loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
                }
            }}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
            disabledReason={responseLoading && !canCancel ? 'Loading' : undefined}
            size="small"
        >
            {canCancel ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}

export function ReloadAll({ iconOnly }: { iconOnly?: boolean }): JSX.Element {
    const { areAnyLoading } = useValues(dataNodeCollectionLogic)
    const { reloadAll } = useActions(dataNodeCollectionLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={reloadAll}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={areAnyLoading ? <Spinner textColored /> : <IconRefresh />}
            disabledReason={areAnyLoading ? 'Loading' : undefined}
        >
            {!iconOnly && 'Reload'}
        </LemonButton>
    )
}

import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { dataNodeCollectionLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '@posthog/query-frontend/utils'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

export function Reload(): JSX.Element {
    const { responseLoading, query } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
                }
            }}
            // Setting the loading icon manually to capture clicks while spinning.
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
            size="small"
        >
            {responseLoading ? 'Cancel' : 'Reload'}
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

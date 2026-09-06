import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

export function Reload(): JSX.Element {
    // Gate on dataLoading, not responseLoading: dataLoading tracks only a user-initiated load,
    // so the 30s autoload poll never shows a spinner or offers a Cancel the user did not ask for.
    const { dataLoading, query } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)

    return (
        <div className="flex gap-2 items-center">
            <LemonButton
                type="secondary"
                onClick={() => loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')}
                // Setting the loading icon manually to capture clicks while spinning.
                icon={dataLoading ? <Spinner textColored /> : <IconRefresh />}
                size="small"
            >
                Reload
            </LemonButton>
            {dataLoading && (
                <LemonButton type="secondary" onClick={cancelQuery} size="small">
                    Cancel
                </LemonButton>
            )}
        </div>
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

import { useActions, useValues } from 'kea'

import { IconRefresh, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

export function Reload(): JSX.Element {
    const { responseLoading, dataLoading, query } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)

    return (
        <div className="flex items-center gap-1">
            {/* Cancel is its own target, so a click aimed at Reload cannot stop the running query. */}
            <LemonButton
                type="secondary"
                onClick={() => loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')}
                icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
                size="small"
                disabledReason={responseLoading ? 'Waiting for the results' : undefined}
                data-attr="reload-query"
            >
                Reload
            </LemonButton>
            {/* Only the main query carries the abort signal, so Cancel shows for it, not for pagination. */}
            {dataLoading && (
                <LemonButton
                    type="secondary"
                    onClick={cancelQuery}
                    icon={<IconX />}
                    size="small"
                    tooltip="Stop this query"
                    data-attr="cancel-query"
                >
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

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

// A fast query can finish before a double click lands, so the button only turns into "Cancel" after this delay.
const CANCEL_ENABLED_AFTER_MS = 1000

export function Reload(): JSX.Element {
    const { responseLoading, query, loadingStart } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)
    const [canCancel, setCanCancel] = useState(false)

    useEffect(() => {
        if (!responseLoading) {
            setCanCancel(false)
            return
        }
        const timeout = window.setTimeout(() => setCanCancel(true), CANCEL_ENABLED_AFTER_MS)
        return () => window.clearTimeout(timeout)
    }, [responseLoading])

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                if (responseLoading) {
                    posthog.capture('data node query cancelled', {
                        query_kind: query.kind,
                        loading_ms: loadingStart ? Math.round(performance.now() - loadingStart) : null,
                    })
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
            {responseLoading && canCancel ? 'Cancel' : 'Reload'}
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

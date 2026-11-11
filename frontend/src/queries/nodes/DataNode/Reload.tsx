import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

export function Reload({ size = 'small' }: Pick<LemonButtonProps, 'size'>): JSX.Element {
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
            size={size}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}

export function ReloadAll({ iconOnly }: { iconOnly?: boolean }): JSX.Element {
    const { areAnyLoading } = useValues(dataNodeCollectionLogic)
    const { reloadAll } = useActions(dataNodeCollectionLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Button
                variant="outline"
                size={iconOnly ? 'icon' : undefined}
                onClick={reloadAll}
                loading={areAnyLoading}
                aria-label={iconOnly ? 'Reload' : undefined}
                tooltip={iconOnly ? 'Reload' : undefined}
            >
                <IconRefresh />
                {!iconOnly && 'Reload'}
            </Button>
        )
    }

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

import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { analyticsListLogic } from './analyticsListLogic'

export function AnalyticsListSelectionBar(): JSX.Element | null {
    const { selectedCount } = useValues(analyticsListLogic)
    const { clearSelection } = useActions(analyticsListLogic)
    if (selectedCount === 0) {
        return null
    }
    return (
        <div className="flex items-center gap-2 pb-2">
            <Text size="xs">{`${selectedCount} selected`}</Text>
            <Button
                variant="outline"
                size="xs"
                onClick={() => clearSelection()}
                data-attr="analytics-list-clear-selection"
            >
                Clear selection
            </Button>
        </div>
    )
}

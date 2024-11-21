import { IconEye } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { metalyticsLogic } from './metalyticsLogic'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)

    if (!instanceId) {
        return null
    }

    return (
        <LemonButton loading={viewCountLoading} type="secondary" icon={<IconEye />} size="small">
            {viewCount === null ? 'Loading...' : `Viewed ${viewCount} times`}
        </LemonButton>
    )
}

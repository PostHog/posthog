import { IconPulse } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { metalyticsLogic } from './metalyticsLogic'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount } = useValues(metalyticsLogic)

    if (!instanceId) {
        return null
    }

    return (
        <>
            <LemonButton
                size="medium"
                icon={
                    <IconWithCount count={viewCount ?? 0}>
                        <IconPulse className="mr-2" />
                    </IconWithCount>
                }
                className="p-0.5"
                tooltip="Learn more about who is using this feature"
            />
        </>
    )
}

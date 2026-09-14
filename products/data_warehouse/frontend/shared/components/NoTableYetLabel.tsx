import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function NoTableYetLabel(): JSX.Element {
    return (
        <Tooltip title="This schema has no PostHog table to query. A sync that returns no rows does not create one. If you expect data here, check this source's settings, then sync again.">
            <span className="text-muted inline-flex items-center gap-1">
                No table yet
                <IconInfo className="text-muted-alt text-base" />
            </span>
        </Tooltip>
    )
}

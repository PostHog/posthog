import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function NoTableYetLabel(): JSX.Element {
    return (
        <Tooltip title="The last sync returned no rows, so there is no table to query yet. PostHog creates the table on the first sync that returns rows. If you expect data, check this source's settings, then sync again.">
            <span className="text-muted inline-flex items-center gap-1">
                No table yet
                <IconInfo className="text-muted-alt text-base" />
            </span>
        </Tooltip>
    )
}

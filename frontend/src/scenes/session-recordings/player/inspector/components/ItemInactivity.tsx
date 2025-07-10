import { IconClock } from '@posthog/icons'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { humanFriendlyDuration } from 'lib/utils'
import { InspectorListItemInactivity } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export function ItemInactivity({ item }: { item: InspectorListItemInactivity }): JSX.Element {
    return (
        <div className="flex w-full items-center justify-center text-xs">
            <LemonDivider className="shrink" />
            <div className="flex flex-1 px-2">
                <IconClock />
                <div className="min-w-30 ml-2 flex-1">
                    {humanFriendlyDuration(item.durationMs / 1000)} of inactivity
                </div>
            </div>
            <LemonDivider className="shrink" />
        </div>
    )
}

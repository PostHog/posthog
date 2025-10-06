import { IconClock } from '@posthog/icons'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { humanFriendlyDuration } from 'lib/utils'
import { InspectorListItemInactivity } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export function ItemInactivity({ item }: { item: InspectorListItemInactivity }): JSX.Element {
    return (
        <div className="w-full text-xs items-center justify-center flex">
            <LemonDivider className="shrink" />
            <div className="flex-1 flex px-2">
                <IconClock />
                <div className="flex-1 min-w-30 ml-2">
                    {humanFriendlyDuration(item.durationMs / 1000)} of inactivity
                </div>
            </div>
            <LemonDivider className="shrink" />
        </div>
    )
}

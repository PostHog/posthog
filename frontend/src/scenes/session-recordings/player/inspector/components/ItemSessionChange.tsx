import { IconArrowLeft, IconArrowRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { InspectorListSessionChange } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { urls } from 'scenes/urls'

export function ItemSessionChange({ item }: { item: InspectorListSessionChange }): JSX.Element | null {
    const targetSession = item.data.previousSessionId || item.data.nextSessionId

    if (!targetSession) {
        return null
    }

    return (
        <div className="w-full text-xs items-center justify-center flex">
            <LemonDivider className="shrink" />
            <div className="flex-1 flex px-2">
                <LemonButton
                    size="xsmall"
                    to={urls.replaySingle(targetSession)}
                    icon={item.tag === '$session_starting' ? <IconArrowLeft /> : <IconArrowRight />}
                    tooltip="PostHog might split user sessions, for example if a session has been idle for a long time. You can jump between these sessions to see the continued journey for the user."
                >
                    Jump to {item.tag === '$session_starting' ? 'previous' : 'next'} session
                </LemonButton>
            </div>
            <LemonDivider className="shrink" />
        </div>
    )
}

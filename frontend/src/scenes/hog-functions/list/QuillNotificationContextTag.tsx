import { IconBell } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { HogFunctionType } from '~/types'

import { eventToHogFunctionContextId } from '../sub-templates/sub-templates'
import { INTERNAL_DESTINATION_CONTEXT } from './HogFunctionsList'

export function QuillNotificationContextTag({ hogFunction }: { hogFunction: HogFunctionType }): JSX.Element | null {
    const eventId = hogFunction.filters?.events?.[0]?.id
    const contextId = eventToHogFunctionContextId(eventId)
    const context = INTERNAL_DESTINATION_CONTEXT[contextId]
    if (!context) {
        return null
    }

    const tooltipTitle = context.url
        ? `Notification managed in ${context.label} settings. Click to go there.`
        : `Notification managed in ${context.label} settings.`

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge render={context.url ? <LinkPrimitive to={context.url} /> : <span tabIndex={0} />}>
                        <IconBell />
                        {context.label}
                    </Badge>
                }
            />
            <TooltipContent>{tooltipTitle}</TooltipContent>
        </Tooltip>
    )
}

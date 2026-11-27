import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

import { HumanizedActivityLogItem } from './humanizeActivity'

/** The avatar of whoever made a change, with their email on hover when the row may reveal it. */
export function QuillActivityLogActor({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const avatar = (
        <QuillPersonAvatar
            name={logItem.name ?? ''}
            email={logItem.email ?? undefined}
            system={logItem.isSystem || logItem.wasImpersonated}
        />
    )

    if (!logItem.emailToReveal) {
        return <span className="flex shrink-0 self-start">{avatar}</span>
    }
    return (
        <Tooltip>
            <TooltipTrigger delay={200} render={<span className="flex shrink-0 self-start" />}>
                {avatar}
            </TooltipTrigger>
            <TooltipContent className="ph-no-capture">{logItem.emailToReveal}</TooltipContent>
        </Tooltip>
    )
}

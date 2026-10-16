import { ReactNode } from 'react'

import { IconLogomark, IconThumbsUp } from '@posthog/icons'
import { Badge, Text } from '@posthog/quill'

import { WaysToUseReveal } from '../WaysToUseReveal'

function SlackMessage({
    avatar,
    name,
    tag,
    children,
}: {
    avatar: ReactNode
    name: string
    tag?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex gap-1.5">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-sm bg-fill-selected text-xxs font-semibold">
                {avatar}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
                <div className="flex items-center gap-1">
                    <Text size="xxs" weight="semibold">
                        {name}
                    </Text>
                    {tag}
                </div>
                {children}
            </div>
        </div>
    )
}

export function SlackIllustration(): JSX.Element {
    return (
        <div className="flex h-full flex-col gap-2 overflow-hidden rounded-tl-md border-t border-l border-border bg-background p-2">
            <Text size="xxs" weight="medium" variant="muted">
                # product
            </Text>
            <SlackMessage avatar="S" name="Sam">
                <Text size="xxs">
                    <span className="font-semibold">@PostHog</span> why did signups drop?
                </Text>
            </SlackMessage>
            <SlackMessage avatar={<IconLogomark className="size-3.5" />} name="PostHog" tag={<Badge>App</Badge>}>
                <Text size="xxs">The new pricing page.</Text>
                <WaysToUseReveal>
                    <span className="inline-flex items-center gap-0.5 rounded-full border border-border bg-fill-selected px-1.5 text-xxs">
                        <IconThumbsUp className="size-2.5" />2
                    </span>
                </WaysToUseReveal>
            </SlackMessage>
        </div>
    )
}

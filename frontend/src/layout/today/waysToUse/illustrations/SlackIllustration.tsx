import { ReactNode } from 'react'

import { IconLogomark } from '@posthog/icons'
import { Text } from '@posthog/quill'

function SlackMessage({
    avatar,
    name,
    children,
}: {
    avatar: ReactNode
    name: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex gap-1.5">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-sm bg-fill-selected text-xxs font-semibold">
                {avatar}
            </span>
            <div className="flex min-w-0 flex-col">
                <Text size="xxs" weight="semibold">
                    {name}
                </Text>
                <Text size="xxs">{children}</Text>
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
                <span className="font-semibold">@PostHog</span> why did signups drop?
            </SlackMessage>
            <SlackMessage avatar={<IconLogomark className="size-3.5" />} name="PostHog">
                Signups fell after the pricing change.
            </SlackMessage>
        </div>
    )
}

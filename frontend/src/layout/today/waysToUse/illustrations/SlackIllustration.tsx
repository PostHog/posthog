import { IconLogomark } from '@posthog/icons'
import { Avatar, AvatarFallback, Badge, Text } from '@posthog/quill'

import { WaysToUsePreviewCallout } from './WaysToUsePreviewCallout'
import { WaysToUsePreviewWindow } from './WaysToUsePreviewWindow'

export function SlackIllustration(): JSX.Element {
    return (
        <>
            <WaysToUsePreviewWindow>
                <div className="flex flex-col gap-2.5 p-3">
                    <div className="flex gap-2">
                        <Avatar size="sm" className="shrink-0">
                            <AvatarFallback className="bg-fill-selected text-xs font-semibold text-foreground">
                                S
                            </AvatarFallback>
                        </Avatar>
                        <div className="flex min-w-0 flex-col">
                            <Text size="xs" weight="semibold">
                                Sam
                            </Text>
                            <Text size="xs">
                                <span className="font-medium text-info-foreground">@PostHog</span> why did signups drop?
                            </Text>
                        </div>
                    </div>
                </div>
            </WaysToUsePreviewWindow>
            <WaysToUsePreviewCallout>
                <div className="flex items-center gap-1.5">
                    <IconLogomark className="size-3.5 shrink-0" />
                    <Text size="xs" weight="semibold">
                        PostHog
                    </Text>
                    <Badge>App</Badge>
                </div>
                <Text size="xs">The new pricing page.</Text>
            </WaysToUsePreviewCallout>
        </>
    )
}

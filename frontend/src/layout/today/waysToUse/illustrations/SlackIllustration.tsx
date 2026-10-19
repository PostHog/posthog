import { IconLogomark } from '@posthog/icons'
import { Badge, Text } from '@posthog/quill'

import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { WaysToUsePreviewCallout } from './WaysToUsePreviewCallout'
import { WaysToUsePreviewWindow } from './WaysToUsePreviewWindow'

export function SlackIllustration(): JSX.Element {
    return (
        <>
            <WaysToUsePreviewWindow title="# growth">
                <div className="flex gap-2 p-3">
                    <TaskUserAvatar
                        user={{ first_name: 'Sam', last_name: '', email: 'sam@example.com' }}
                        className="shrink-0"
                    />
                    <div className="flex min-w-0 flex-col">
                        <Text size="xs" weight="semibold">
                            Sam
                        </Text>
                        <Text size="xs">
                            <span className="font-medium text-info-foreground">@PostHog</span> why did signups drop?
                        </Text>
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
                    <Text size="xxs" variant="muted">
                        12:45
                    </Text>
                </div>
                <div className="flex items-center gap-2">
                    <Text size="xs">The pricing change.</Text>
                    <svg viewBox="0 0 120 20" className="h-5 w-12 shrink-0 text-destructive-foreground" aria-hidden>
                        <polyline
                            points="0,6 15,5 30,7 45,4 60,5 75,6 85,12 100,15 120,16"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        />
                    </svg>
                </div>
            </WaysToUsePreviewCallout>
        </>
    )
}

import { IconCheck, IconMCP } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { WaysToUsePreviewCallout } from './WaysToUsePreviewCallout'
import { WaysToUsePreviewWindow } from './WaysToUsePreviewWindow'

export function McpIllustration(): JSX.Element {
    return (
        <>
            <WaysToUsePreviewWindow>
                <div className="flex items-center gap-1 border-b border-border px-3 py-2">
                    <span className="size-1.5 rounded-full bg-border" />
                    <span className="size-1.5 rounded-full bg-border" />
                    <span className="size-1.5 rounded-full bg-border" />
                </div>
                <div className="flex flex-col p-3">
                    <div className="self-end rounded-lg bg-fill-selected px-2 py-1">
                        <Text size="xs">Which flags are stale?</Text>
                    </div>
                </div>
            </WaysToUsePreviewWindow>
            <WaysToUsePreviewCallout>
                <div className="flex items-center gap-1.5">
                    <IconMCP className="size-3.5 shrink-0" />
                    <Text size="xs" weight="semibold">
                        PostHog MCP
                    </Text>
                    <IconCheck className="size-3.5 shrink-0 text-success-foreground" />
                </div>
                <Text size="xs" variant="muted" className="font-mono">
                    feature-flag-get-all
                </Text>
            </WaysToUsePreviewCallout>
        </>
    )
}

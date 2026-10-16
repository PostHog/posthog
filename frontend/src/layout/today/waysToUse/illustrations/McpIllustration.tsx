import { IconCheck, IconMCP } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { WaysToUsePreviewCallout } from './WaysToUsePreviewCallout'
import { WaysToUsePreviewWindow } from './WaysToUsePreviewWindow'

export function McpIllustration(): JSX.Element {
    return (
        <>
            <WaysToUsePreviewWindow title="agent">
                <div className="flex flex-col gap-2 p-3">
                    <div className="self-end rounded-lg bg-fill-selected px-2 py-1">
                        <Text size="xs">Who's on this flag?</Text>
                    </div>
                    <Text size="xs">No one in 30 days.</Text>
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

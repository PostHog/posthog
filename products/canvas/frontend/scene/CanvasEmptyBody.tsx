import { IconPalette } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

/** The body of a canvas with nothing to render yet. The web app only views canvases, so it points to the MCP server. */
export function CanvasEmptyBody({ notice }: { notice?: string }): JSX.Element {
    return (
        <Empty className="h-full border-0">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconPalette />
                </EmptyMedia>
                <EmptyTitle>Nothing to show yet</EmptyTitle>
                <EmptyDescription>
                    {notice ?? 'Ask your agent to build this canvas with the PostHog MCP server.'}
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}

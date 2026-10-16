import { IconCheck, IconMCP } from '@posthog/icons'
import { Text } from '@posthog/quill'

export function McpIllustration(): JSX.Element {
    return (
        <div className="flex h-full flex-col overflow-hidden rounded-tl-md border-t border-l border-border bg-background">
            <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
                <span className="size-1.5 rounded-full bg-border" />
                <span className="size-1.5 rounded-full bg-border" />
                <span className="size-1.5 rounded-full bg-border" />
                <Text size="xxs" variant="muted" className="ml-1 truncate font-mono">
                    agent
                </Text>
            </div>
            <div className="flex min-w-0 flex-col gap-1.5 p-2">
                <div className="self-end rounded-md bg-fill-selected px-1.5 py-1">
                    <Text size="xxs">Which flags can I remove?</Text>
                </div>
                <div className="flex min-w-0 items-center gap-1 text-muted-foreground">
                    <IconMCP className="size-3 shrink-0" />
                    <Text size="xxs" variant="muted" className="truncate font-mono">
                        feature-flag-get-all
                    </Text>
                    <IconCheck className="size-3 shrink-0" />
                </div>
                <Text size="xxs">3 flags are fully rolled out. I can open a cleanup PR.</Text>
            </div>
        </div>
    )
}

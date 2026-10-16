import { IconApps, IconChat, IconGridMasonry, IconHome } from '@posthog/icons'
import { Dot, Text } from '@posthog/quill'

export function WebAppIllustration(): JSX.Element {
    return (
        <div className="flex h-full overflow-hidden rounded-tl-md border-t border-l border-border bg-background">
            <div className="flex flex-col items-center gap-2.5 border-r border-border bg-chrome px-1.5 py-2 text-muted-foreground">
                <IconHome className="size-3.5 text-foreground" />
                <IconChat className="size-3.5" />
                <IconGridMasonry className="size-3.5" />
                <IconApps className="size-3.5" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-2 p-2">
                <div className="flex flex-col">
                    <Text size="xs" weight="semibold">
                        Good morning
                    </Text>
                    <Text size="xxs" variant="muted">
                        2 things changed
                    </Text>
                </div>
                <div className="flex items-center gap-1.5 rounded-sm border border-border px-1.5 py-1">
                    <Dot variant="destructive" />
                    <Text size="xxs">Errors doubled</Text>
                </div>
                <div className="flex items-center gap-1.5 rounded-sm border border-border px-1.5 py-1">
                    <Dot variant="success" />
                    <Text size="xxs">Signups are up</Text>
                </div>
            </div>
        </div>
    )
}

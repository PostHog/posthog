import { IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

export interface QuillTeamsChannelPair {
    team_id: string
    team_name?: string | null
    channel_id: string
    channel_name?: string | null
    isShared: boolean
}

export function QuillTeamsChannelRow({
    pair,
    onRemove,
    isLoading,
    adminRestrictionReason,
}: {
    pair: QuillTeamsChannelPair
    onRemove: () => void
    isLoading: boolean
    adminRestrictionReason: string | null
}): JSX.Element {
    return (
        <Item variant="outline" size="sm">
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{pair.team_name || pair.team_id}</ItemTitle>
                <div className="flex flex-wrap items-center gap-2">
                    <ItemDescription className="truncate">#{pair.channel_name || pair.channel_id}</ItemDescription>
                    {pair.isShared && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge variant="completed" tabIndex={0} />}>
                                Shared · polled
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                Shared channels don't push messages to bots, so PostHog polls them via Microsoft Graph
                                every minute to pick up new messages.
                            </TooltipContent>
                        </Tooltip>
                    )}
                </div>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="destructive-outline"
                    size="icon"
                    aria-label="Remove channel"
                    tooltip="Remove channel"
                    onClick={onRemove}
                    loading={isLoading}
                    disabledReason={adminRestrictionReason || (isLoading ? 'Removing...' : undefined)}
                >
                    <IconTrash />
                </Button>
            </ItemActions>
        </Item>
    )
}

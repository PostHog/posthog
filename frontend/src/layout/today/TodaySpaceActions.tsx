import { useActions, useValues } from 'kea'

import { IconEllipsis, IconGear, IconCopy, IconStar, IconStarFilled } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { todaySpacesLogic } from './todaySpacesLogic'

export function TodaySpaceActions({ space }: { space: ChannelDTOApi }): JSX.Element {
    const { pendingSpaceIds } = useValues(todaySpacesLogic)
    const { toggleStar, copySpaceLink } = useActions(todaySpacesLogic)
    const reportMenuOpen = useTodayPreviewMenuReport()
    const saving = pendingSpaceIds.includes(space.id)
    const menuLabel = saving ? 'Saving your last change' : 'More actions'

    return (
        <DropdownMenu onOpenChange={reportMenuOpen}>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label={menuLabel}
                                    loading={saving}
                                    data-attr="today-space-row-menu"
                                />
                            }
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent>{menuLabel}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-48">
                {space.system_role !== 'personal' && (
                    <DropdownMenuItem
                        onClick={() => toggleStar(space.id, !space.starred)}
                        data-attr="today-space-row-star"
                    >
                        {space.starred ? <IconStarFilled /> : <IconStar />}
                        {space.starred ? 'Unstar space' : 'Star space'}
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => copySpaceLink(space.id)} data-attr="today-space-row-copy-link">
                    <IconCopy />
                    Copy link
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={<Button size="row" left render={<LinkPrimitive to={urls.taskSpaceSettings(space.id)} />} />}
                    data-attr="today-space-row-settings"
                >
                    <IconGear />
                    Space settings
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

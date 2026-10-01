import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { DROPDOWN_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySessionActionItems } from './TodaySessionActionItems'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionMenuTarget } from './todayWorkItems'

interface TodaySessionMenuProps {
    target: TodaySessionMenuTarget
    surface: TodaySessionSurface
}

/** The "…" menu. Its dialogs belong to whoever owns `target.menuId`, which renders `TodaySessionDialogs`. */
export function TodaySessionMenu({ target, surface }: TodaySessionMenuProps): JSX.Element {
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const reportMenuOpen = useTodayPreviewMenuReport()
    const saving = pendingSessionIds.includes(target.sessionId)
    const label = saving ? 'Saving your last change' : 'More actions'

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
                                    aria-label={label}
                                    loading={saving}
                                    data-attr="today-session-menu"
                                />
                            }
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-56">
                <TodaySessionActionItems
                    parts={DROPDOWN_PARTS}
                    target={target}
                    surface={surface}
                    dataAttrPrefix="today-session"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

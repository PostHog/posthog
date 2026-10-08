import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { CONTEXT_PARTS, SHEET_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySheetMenu } from './TodaySheetMenu'
import { todayShellLogic } from './todayShellLogic'
import { TodaySpaceActions } from './TodaySpaceActions'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

/** A space row's actions on right-click, the same list its hover card shows, like PostHog Desktop. */
export function TodaySpaceContextMenu({ space, children }: { space: ChannelDTOApi; children: ReactNode }): JSX.Element {
    const reportMenuOpen = useTodayPreviewMenuReport()
    const { phoneLayout } = useValues(todayShellLogic)
    const { touchMenuOpened } = useActions(todaySpacesLogic)
    const [sheetOpen, setSheetOpen] = useState(false)

    if (phoneLayout) {
        return (
            <>
                <ContextMenu
                    open={false}
                    onOpenChange={(next) => {
                        if (next) {
                            setSheetOpen(true)
                            touchMenuOpened('space')
                        }
                    }}
                >
                    <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
                </ContextMenu>
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title={spaceLabel(space)}>
                    <TodaySpaceActions parts={SHEET_PARTS} space={space} dataAttrPrefix="today-space-sheet" />
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <ContextMenu onOpenChange={reportMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
            <ContextMenuContent className="w-56">
                <TodaySpaceActions parts={CONTEXT_PARTS} space={space} dataAttrPrefix="today-space-context" />
            </ContextMenuContent>
        </ContextMenu>
    )
}

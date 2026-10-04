import { ReactNode } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { CONTEXT_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { TodaySpaceActions } from './TodaySpaceActions'

/** A space row's actions on right-click, the same list its hover card shows, like PostHog Desktop. */
export function TodaySpaceContextMenu({ space, children }: { space: ChannelDTOApi; children: ReactNode }): JSX.Element {
    const reportMenuOpen = useTodayPreviewMenuReport()
    return (
        <ContextMenu onOpenChange={reportMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>{children}</ContextMenuTrigger>
            <ContextMenuContent className="w-56">
                <TodaySpaceActions parts={CONTEXT_PARTS} space={space} dataAttrPrefix="today-space-context" />
            </ContextMenuContent>
        </ContextMenu>
    )
}

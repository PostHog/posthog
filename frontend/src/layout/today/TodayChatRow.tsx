import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { TodayChatActionItems } from './TodayChatActionItems'
import { CONTEXT_PARTS, SHEET_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { chatPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodaySessionIcon } from './TodaySessionIcon'
import { TodaySheetMenu } from './TodaySheetMenu'
import { todayShellLogic } from './todayShellLogic'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem } from './todayWorkItems'

interface TodayChatRowProps {
    item: TodayWorkItem
    dataAttr: string
    optionValue: string
}

export function TodayChatRow({ item, dataAttr, optionValue }: TodayChatRowProps): JSX.Element {
    const { location, searchParams } = useValues(router)
    const reportMenuOpen = useTodayPreviewMenuReport()
    const preview = useMemo(() => chatPreview(item), [item])
    const { phoneLayout } = useValues(todayShellLogic)
    const { touchMenuOpened } = useActions(todaySpacesLogic)
    const [sheetOpen, setSheetOpen] = useState(false)

    const row = (
        <TodayPreviewTrigger payload={preview}>
            <TodaySpacesRow
                label={preview.title}
                icon={<TodaySessionIcon item={item} />}
                to={urls.ai(item.id)}
                active={location.pathname.endsWith('/ai') && searchParams.chat === item.id}
                dataAttr={dataAttr}
                optionValue={optionValue}
            />
        </TodayPreviewTrigger>
    )

    if (phoneLayout) {
        return (
            <>
                <ContextMenu
                    open={false}
                    onOpenChange={(next) => {
                        if (next) {
                            setSheetOpen(true)
                            touchMenuOpened('chat')
                        }
                    }}
                >
                    <ContextMenuTrigger render={<div className="min-w-0" />}>{row}</ContextMenuTrigger>
                </ContextMenu>
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title={preview.title}>
                    <TodayChatActionItems parts={SHEET_PARTS} chatId={item.id} dataAttrPrefix="today-chat-sheet" />
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <ContextMenu onOpenChange={reportMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>{row}</ContextMenuTrigger>
            <ContextMenuContent className="w-56">
                <TodayChatActionItems parts={CONTEXT_PARTS} chatId={item.id} dataAttrPrefix="today-chat-context" />
            </ContextMenuContent>
        </ContextMenu>
    )
}

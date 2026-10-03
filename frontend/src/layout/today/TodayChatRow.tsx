import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { TodayChatActionItems } from './TodayChatActionItems'
import { CONTEXT_PARTS } from './todayMenuParts'
import { useTodayPreviewMenuReport } from './todayPreviewCardContext'
import { chatPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodaySessionIcon } from './TodaySessionIcon'
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

    return (
        <ContextMenu onOpenChange={reportMenuOpen}>
            <ContextMenuTrigger render={<div className="min-w-0" />}>
                <TodayPreviewTrigger payload={preview}>
                    <TodaySpacesRow
                        label={preview.title}
                        icon={<TodaySessionIcon item={item} />}
                        to={urls.ai(item.id)}
                        active={location.pathname.endsWith('/ai') && searchParams.chat === item.id}
                        dataAttr={dataAttr}
                        weight="regular"
                        optionValue={optionValue}
                    />
                </TodayPreviewTrigger>
            </ContextMenuTrigger>
            <ContextMenuContent className="w-56">
                <TodayChatActionItems parts={CONTEXT_PARTS} chatId={item.id} dataAttrPrefix="today-chat-context" />
            </ContextMenuContent>
        </ContextMenu>
    )
}

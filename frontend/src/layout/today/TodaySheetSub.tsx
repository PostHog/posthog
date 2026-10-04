import { ReactNode, useId } from 'react'
import { createPortal } from 'react-dom'

import { IconChevronRight } from '@posthog/icons'
import { ItemMenuItem, cn } from '@posthog/quill'

import { useTodaySheetMenu } from './todaySheetMenuContext'

interface TodaySheetSubProps {
    label: ReactNode
    title: string
    value?: string
    narrowed?: boolean
    dataAttr?: string
    children: ReactNode
}

export function TodaySheetSub({
    label,
    title,
    value,
    narrowed = false,
    dataAttr,
    children,
}: TodaySheetSubProps): JSX.Element {
    const sheet = useTodaySheetMenu()
    const pageId = useId()
    const open = sheet?.activePageId === pageId

    return (
        <>
            <ItemMenuItem
                className="flex-nowrap text-base"
                aria-haspopup="menu"
                onClick={() => sheet?.openPage(pageId, title)}
                data-attr={dataAttr}
            >
                <span className="flex min-w-0 items-center gap-2">{label}</span>
                {value && (
                    <span
                        className={cn(
                            'ml-auto min-w-0 truncate pl-4 text-right',
                            narrowed ? 'text-primary' : 'text-muted-foreground'
                        )}
                    >
                        {value}
                    </span>
                )}
                <IconChevronRight className={cn('shrink-0 text-muted-foreground', !value && 'ml-auto')} />
            </ItemMenuItem>
            {open && sheet?.pageContainer && createPortal(children, sheet.pageContainer)}
        </>
    )
}

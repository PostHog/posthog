import './CardMeta.scss'

import clsx from 'clsx'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'

import { InsightColor } from '~/types'

export interface QuillCardMetaProps {
    ribbonColor?: InsightColor | null
    topHeading?: JSX.Element | null
    content: JSX.Element
    refreshControl?: JSX.Element | null
    headerStatus?: JSX.Element | null
    /** Rows of the "more" menu. No menu is shown without them. */
    menuItems?: JSX.Element | null
    menuTooltip?: string
    onMouseDown?: React.MouseEventHandler<HTMLDivElement>
}

export function QuillCardMeta({
    ribbonColor,
    topHeading,
    content,
    refreshControl,
    headerStatus,
    menuItems,
    menuTooltip = 'More',
    onMouseDown,
}: QuillCardMetaProps): JSX.Element {
    const controls = (
        <div className="CardMeta__controls">
            {refreshControl}
            {headerStatus}
            {menuItems ? (
                <DropdownMenu
                    onOpenChange={(open, details) => {
                        if (closesIntoLemonPopover(open, details)) {
                            details.cancel()
                        }
                    }}
                >
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon"
                                aria-label={menuTooltip}
                                tooltip={menuTooltip}
                                data-attr="more-button"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">{menuItems}</DropdownMenuContent>
                </DropdownMenu>
            ) : null}
        </div>
    )

    return (
        <div
            className={clsx(
                'CardMeta CardMeta--compact',
                headerStatus && 'CardMeta--header-status',
                onMouseDown && 'cursor-grab'
            )}
            onMouseDown={onMouseDown}
        >
            <div className="CardMeta__primary">
                {ribbonColor && ribbonColor !== InsightColor.White && (
                    <div className={clsx('CardMeta__ribbon', ribbonColor)} />
                )}
                <div className="CardMeta__main">
                    <div className="CardMeta__top">
                        <div className="CardMeta__heading">{topHeading}</div>
                        {!headerStatus && controls}
                    </div>
                    {content}
                </div>
                {headerStatus && controls}
            </div>
            <div className="CardMeta__divider" />
        </div>
    )
}

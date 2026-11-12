import './CardMeta.scss'

import clsx from 'clsx'

import { CardAction, CardHeader, Text } from '@posthog/quill'

import { InsightColor } from '~/types'

import { QuillCardMoreMenu } from './QuillCardMoreMenu'

export interface QuillCardMetaProps {
    ribbonColor?: InsightColor | null
    topHeading?: JSX.Element | null
    /** A `CardTitle`, optionally followed by a `CardDescription`. */
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
    return (
        <div
            className={clsx(
                'CardMeta CardMeta--compact CardMeta--quill',
                headerStatus && 'CardMeta--header-status',
                onMouseDown && 'cursor-grab'
            )}
            onMouseDown={onMouseDown}
        >
            <div className="flex">
                {ribbonColor && ribbonColor !== InsightColor.White && (
                    <div className={clsx('CardMeta__ribbon', ribbonColor)} />
                )}
                <CardHeader className="min-w-0 flex-1 gap-y-0 py-2">
                    {topHeading && (
                        <Text
                            size="xxs"
                            variant="muted"
                            weight="semibold"
                            className="uppercase tracking-wider empty:hidden"
                            render={<div />}
                        >
                            {topHeading}
                        </Text>
                    )}
                    {content}
                    <CardAction className="row-1 flex items-center gap-1">
                        {refreshControl}
                        {headerStatus}
                        {menuItems ? <QuillCardMoreMenu items={menuItems} tooltip={menuTooltip} /> : null}
                    </CardAction>
                </CardHeader>
            </div>
            <div className="CardMeta__divider" />
        </div>
    )
}

import './CardMeta.scss'

import clsx from 'clsx'

import { Text } from '@posthog/quill'

import { InsightColor } from '~/types'

import { QuillCardMoreMenu } from './QuillCardMoreMenu'

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
            {menuItems ? <QuillCardMoreMenu items={menuItems} tooltip={menuTooltip} /> : null}
        </div>
    )

    return (
        <div
            className={clsx(
                'CardMeta CardMeta--compact CardMeta--quill',
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
                        <div className="CardMeta__heading">
                            <Text
                                size="xxs"
                                variant="muted"
                                weight="semibold"
                                className="font-sans uppercase tracking-wider"
                                render={<div />}
                            >
                                {topHeading}
                            </Text>
                        </div>
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

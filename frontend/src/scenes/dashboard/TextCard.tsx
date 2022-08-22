import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'
import clsx from 'clsx'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    body: string
    children?: JSX.Element
}

export function TextCardInternal(
    { body, showResizeHandles, canResizeWidth, children, className, ...divProps }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className={clsx('TextCard border rounded', className)} data-attr="text-card" {...divProps} ref={ref}>
            <Textfit mode="single" min={32} max={120}>
                <div>{body}</div>
            </Textfit>
            {showResizeHandles && (
                <>
                    {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                    <ResizeHandle1D orientation="horizontal" />
                    {canResizeWidth ? <ResizeHandle2D /> : null}
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef(TextCardInternal) as typeof TextCardInternal

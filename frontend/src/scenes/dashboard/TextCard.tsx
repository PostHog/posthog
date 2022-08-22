import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    body: string
    children?: JSX.Element
}

export function TextCardInternal(
    { body, showResizeHandles, canResizeWidth, children, ...divProps }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className="TextCard border rounded" data-attr="text-card" {...divProps} ref={ref}>
            <Textfit mode="single" min={32} max={120}>
                <div className="flex items-center justify-center">{body}</div>
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

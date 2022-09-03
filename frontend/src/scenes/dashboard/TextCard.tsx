import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'
import clsx from 'clsx'
import { InsightColor } from '~/types'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    body: string
    color: string
    children?: JSX.Element
}

function TextCardHeader({ color, showEditingControls }: { color: string; showEditingControls: boolean }): JSX.Element {
    return (
        <div className="min-h-4 flex flex-col items-center w-full">
            <div className="w-full flex flex-row pt-2 px-2">
                {color &&
                    color !== InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('DashboardCard__ribbon', color)} />
                    )}
                <div className="flex flex-1 justify-end">
                    {showEditingControls && (
                        <More
                            overlay={
                                <>
                                    <LemonButton status="stealth" fullWidth>
                                        Edit text
                                    </LemonButton>
                                </>
                            }
                        />
                    )}
                </div>
            </div>
            <LemonDivider />
        </div>
    )
}

export function TextCardInternal(
    { body, color, showResizeHandles, canResizeWidth, children, className, ...divProps }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className={clsx('TextCard border rounded', className)} data-attr="text-card" {...divProps} ref={ref}>
            <TextCardHeader color={color} showEditingControls={true} />
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

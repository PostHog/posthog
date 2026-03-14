import clsx from 'clsx'
import React from 'react'

import { IconExternal } from '@posthog/icons'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'

import { DashboardPlacement, DashboardWidgetModel, DashboardWidgetType } from '~/types'

const WIDGET_TYPE_LABELS: Record<DashboardWidgetType, string> = {
    [DashboardWidgetType.Experiment]: 'Experiment',
    [DashboardWidgetType.Logs]: 'Logs',
    [DashboardWidgetType.ErrorTracking]: 'Error tracking',
    [DashboardWidgetType.SessionReplays]: 'Session replays',
    [DashboardWidgetType.SurveyResponses]: 'Survey responses',
}

export interface WidgetCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    widget: DashboardWidgetModel
    placement: DashboardPlacement
    children?: React.ReactNode
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: () => void
    moreButtonOverlay?: MoreProps['overlay']
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    openUrl?: string
    contentRenderer: React.ReactNode
}

function WidgetCardInternal(
    {
        widget,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        placement,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        openUrl,
        contentRenderer,
        ...divProps
    }: WidgetCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const shouldHideMoreButton = placement === DashboardPlacement.Public

    return (
        <div
            className={clsx('WidgetCard bg-surface-primary border rounded flex flex-col overflow-hidden', className)}
            data-attr="widget-card"
            {...divProps}
            ref={ref}
        >
            <div
                className={clsx(
                    'CardMeta flex items-center justify-between px-4 py-2 border-b shrink-0',
                    onDragHandleMouseDown && 'cursor-grab'
                )}
                onMouseDown={onDragHandleMouseDown}
            >
                <span className="text-xs font-semibold text-muted uppercase tracking-wide">
                    {WIDGET_TYPE_LABELS[widget.widget_type]}
                </span>
                <div className="flex items-center gap-1">
                    {openUrl && (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconExternal />}
                            to={openUrl}
                            targetBlank={false}
                            tooltip="Open full view"
                        />
                    )}
                    {moreButtonOverlay && !shouldHideMoreButton && <More overlay={moreButtonOverlay} />}
                </div>
            </div>

            <div className="flex-1 overflow-auto min-h-0">{contentRenderer}</div>

            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const WidgetCard = React.forwardRef<HTMLDivElement, WidgetCardProps>(WidgetCardInternal)

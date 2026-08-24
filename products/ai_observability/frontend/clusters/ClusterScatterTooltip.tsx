import { TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'

export interface ClusterScatterTooltipProps {
    color: string
    title: string
    subtitle?: string
    footer?: string
}

export function ClusterScatterTooltip({ color, title, subtitle, footer }: ClusterScatterTooltipProps): JSX.Element {
    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 min-w-0 font-semibold">
                <TooltipSwatch color={color} />
                <span className="truncate">{title}</span>
            </div>
            {subtitle ? <div className="opacity-60">{subtitle}</div> : null}
            {footer ? <TooltipFooter>{footer}</TooltipFooter> : null}
        </TooltipSurface>
    )
}

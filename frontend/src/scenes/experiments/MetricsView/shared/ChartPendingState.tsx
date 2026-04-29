import { IconRefresh } from '@posthog/icons'

interface ChartPendingStateProps {
    height: number
}

export function ChartPendingState({ height }: ChartPendingStateProps): JSX.Element {
    return (
        <div
            className="flex items-center justify-center gap-2 text-secondary text-[14px] font-normal"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: `${height}px` }}
        >
            <IconRefresh />
            <span>No results yet — refresh to compute</span>
        </div>
    )
}

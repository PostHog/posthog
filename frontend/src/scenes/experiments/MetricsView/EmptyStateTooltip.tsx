import { NoResultEmptyState } from './NoResultEmptyState'

interface EmptyStateTooltipProps {
    tooltipPosition: { x: number; y: number }
    error: any
    metric: any
    setEmptyStateTooltipVisible: (visible: boolean) => void
}

export function EmptyStateTooltip({
    tooltipPosition,
    error,
    metric,
    setEmptyStateTooltipVisible,
}: EmptyStateTooltipProps): JSX.Element {
    return (
        <div
            className="fixed -translate-x-1/2 -translate-y-full bg-[var(--bg-surface-primary)] border border-[var(--border-primary)] p-2 rounded-md text-[13px] shadow-md z-[100] min-w-[200px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: tooltipPosition.x,
                top: tooltipPosition.y,
            }} // Dynamic positioning based on mouse position
            onMouseEnter={() => setEmptyStateTooltipVisible(true)}
            onMouseLeave={() => setEmptyStateTooltipVisible(false)}
        >
            <NoResultEmptyState error={error} metric={metric} />
        </div>
    )
}

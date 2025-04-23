interface ChartLoadingStateProps {
    height: number
}

export function ChartLoadingState({ height }: ChartLoadingStateProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="flex items-center justify-center text-[14px] font-normal" style={{ height: `${height}px` }}>
            <span>Results loading&hellip;</span>
        </div>
    )
}

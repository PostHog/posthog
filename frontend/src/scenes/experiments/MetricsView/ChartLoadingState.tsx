interface ChartLoadingStateProps {
    width: number
    height: number
}

export function ChartLoadingState({ width, height }: ChartLoadingStateProps): JSX.Element {
    return (
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
            <foreignObject
                x={width / 2 - 100} // Center the 200px wide container
                y={height / 2 - 10} // Roughly center vertically
                width="200"
                height="20"
            >
                <div className="flex items-center justify-center text-secondary cursor-default text-[10px] font-normal">
                    <span>Results loading&hellip;</span>
                </div>
            </foreignObject>
        </svg>
    )
}

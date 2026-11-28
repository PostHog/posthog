import { ChartFrameSkeleton, SkeletonSvg } from '../../ChartFrameSkeleton'

// Each box as [whisker top, box top, median, box bottom, whisker bottom], out of 100.
const BOXES = [
    [20, 34, 44, 56, 72],
    [38, 50, 58, 66, 80],
    [50, 60, 66, 74, 86],
]

export function BoxPlotLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            <SkeletonSvg viewBox="0 0 300 100">
                {BOXES.map(([top, boxTop, median, boxBottom, bottom], index) => {
                    const center = 50 + index * 100
                    return (
                        <g
                            key={index}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            vectorEffect="non-scaling-stroke"
                        >
                            <line x1={center} x2={center} y1={top} y2={bottom} vectorEffect="non-scaling-stroke" />
                            <rect
                                x={center - 30}
                                y={boxTop}
                                width="60"
                                height={boxBottom - boxTop}
                                fill="currentColor"
                                fillOpacity="0.4"
                                vectorEffect="non-scaling-stroke"
                            />
                            <line
                                x1={center - 30}
                                x2={center + 30}
                                y1={median}
                                y2={median}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    )
                })}
            </SkeletonSvg>
        </ChartFrameSkeleton>
    )
}

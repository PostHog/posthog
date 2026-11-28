import { ChartFrameSkeleton, SkeletonSvg } from '../../ChartFrameSkeleton'

const LINES = [
    [40, 20],
    [62, 48],
    [70, 76],
]

export function SlopeLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            <SkeletonSvg viewBox="0 0 300 100">
                {LINES.map(([from, to]) => (
                    <line
                        key={from}
                        x1="10"
                        x2="250"
                        y1={from}
                        y2={to}
                        stroke="currentColor"
                        strokeWidth="3"
                        vectorEffect="non-scaling-stroke"
                    />
                ))}
            </SkeletonSvg>
        </ChartFrameSkeleton>
    )
}

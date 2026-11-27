import { ChartFrameSkeleton, SkeletonSvg } from '../../ChartFrameSkeleton'

// Fixed points, so every load draws the same picture.
const POINTS = [
    [20, 72],
    [42, 60],
    [60, 78],
    [85, 52],
    [104, 64],
    [130, 44],
    [150, 58],
    [172, 36],
    [196, 48],
    [215, 28],
    [238, 40],
    [258, 22],
    [280, 30],
]

export function ScatterLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            <SkeletonSvg viewBox="0 0 300 100" className="size-full overflow-visible">
                {POINTS.map(([x, y]) => (
                    <ellipse key={x} cx={x} cy={y} rx="4" ry="5" fill="currentColor" />
                ))}
            </SkeletonSvg>
        </ChartFrameSkeleton>
    )
}

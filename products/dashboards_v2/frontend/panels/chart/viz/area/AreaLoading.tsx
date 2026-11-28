import { ChartFrameSkeleton, SkeletonSvg } from '../../ChartFrameSkeleton'

const CURVE = 'M0 70 C30 66 45 50 75 54 S120 72 150 48 S200 22 225 32 S275 16 300 12'

export function AreaLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            <SkeletonSvg viewBox="0 0 300 100">
                <path d={`${CURVE} V100 H0 Z`} fill="currentColor" opacity="0.5" />
                <path d={CURVE} fill="none" stroke="currentColor" strokeWidth="3" vectorEffect="non-scaling-stroke" />
            </SkeletonSvg>
        </ChartFrameSkeleton>
    )
}

import { SkeletonSvg } from '../../ChartFrameSkeleton'

export function GaugeLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 items-center justify-center" aria-busy="true">
            <SkeletonSvg viewBox="0 0 100 60" className="aspect-[5/3] max-h-full w-3/5">
                <path
                    d="M10 55 A40 40 0 1 1 90 55"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="8"
                    strokeLinecap="round"
                />
            </SkeletonSvg>
        </div>
    )
}

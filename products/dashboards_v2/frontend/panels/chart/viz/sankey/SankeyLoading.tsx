import { SkeletonSvg } from '../../ChartFrameSkeleton'

// Bands from one source node on the left to three target nodes on the right.
const BANDS = [
    'M8 10 C150 10 150 8 292 8 V44 C150 44 150 50 8 50 Z',
    'M8 52 C150 52 150 52 292 52 V72 C150 72 150 74 8 74 Z',
    'M8 76 C150 76 150 78 292 78 V92 C150 92 150 90 8 90 Z',
]

export function SankeyLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1" aria-busy="true">
            <SkeletonSvg viewBox="0 0 300 100">
                <rect x="0" y="10" width="8" height="80" fill="currentColor" />
                {BANDS.map((band) => (
                    <path key={band} d={band} fill="currentColor" opacity="0.5" />
                ))}
                <rect x="292" y="8" width="8" height="36" fill="currentColor" />
                <rect x="292" y="52" width="8" height="20" fill="currentColor" />
                <rect x="292" y="78" width="8" height="14" fill="currentColor" />
            </SkeletonSvg>
        </div>
    )
}

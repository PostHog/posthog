import { ChartFrameSkeleton } from '../../ChartFrameSkeleton'

export function LineLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            <svg
                viewBox="0 0 300 100"
                preserveAspectRatio="none"
                className="size-full animate-pulse text-primary opacity-15 motion-reduce:animate-none"
                aria-hidden="true"
            >
                <path
                    d="M0 78 C30 74 45 60 75 64 S120 82 150 58 S200 30 225 42 S275 24 300 18"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
        </ChartFrameSkeleton>
    )
}

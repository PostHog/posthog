import './WrappingLoadingSkeleton.scss'

import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { cn } from 'lib/utils/css-classes'

export interface WrappingLoadingSkeletonProps {
    fullWidth?: boolean
    children: React.ReactNode
    className?: string
}
export function WrappingLoadingSkeleton({
    children,
    fullWidth = false,
    className,
}: WrappingLoadingSkeletonProps): JSX.Element {
    const ref = useCancelAnimationsOnUnmount<HTMLDivElement>()
    return (
        <div
            ref={ref}
            className={cn(
                'wrapping-loading-skeleton [&>*]:opacity-0 rounded flex flex-col gap-px w-fit overflow-hidden',
                fullWidth && 'w-full',
                className
            )}
            aria-hidden
            data-attr="wrapping-loading-skeleton"
        >
            <span className="flex">{children}</span>
        </div>
    )
}

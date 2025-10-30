import './WrappingLoadingSkeleton.scss'

import { cn } from 'lib/utils/css-classes'

interface WrappingLoadingSkeletonProps {
    fullWidth?: boolean
    children: React.ReactNode
    className?: string
}
export function WrappingLoadingSkeleton({
    children,
    fullWidth = false,
    className,
}: WrappingLoadingSkeletonProps): JSX.Element {
    return (
        <div
            className={cn(
                'wrapping-loading-skeleton [&>*]:opacity-0 rounded flex flex-col gap-px w-fit',
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

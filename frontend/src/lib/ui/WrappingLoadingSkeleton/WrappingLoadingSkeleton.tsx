import './WrappingLoadingSkeleton.scss'

import { cn } from 'lib/utils/css-classes'

interface WrappingLoadingSkeletonProps {
    fullWidth?: boolean
    children: React.ReactNode
    className?: string
    /** Adds vertical inset so skeleton doesn't fill bounds - prevents rounded corners from touching when stacked */
    inset?: boolean
}
export function WrappingLoadingSkeleton({
    children,
    fullWidth = false,
    className,
    inset = false,
}: WrappingLoadingSkeletonProps): JSX.Element {
    return (
        <div
            className={cn(
                'wrapping-loading-skeleton [&>*]:opacity-0 rounded flex flex-col gap-px w-fit',
                fullWidth && 'w-full',
                inset && 'py-0.5',
                className
            )}
            aria-hidden
            data-attr="wrapping-loading-skeleton"
        >
            <span className="flex">{children}</span>
        </div>
    )
}

import { cn } from 'lib/utils/css-classes'
import './WrappingLoadingSkeleton.scss'

interface WrappingLoadingSkeletonProps {
    fullWidth?: boolean
    children: React.ReactNode
}
export function WrappingLoadingSkeleton({ children, fullWidth = false }: WrappingLoadingSkeletonProps): JSX.Element {
    return (
        <div
            className={cn(
                'wrapping-loading-skeleton [&>*]:opacity-0 rounded flex flex-col gap-px w-fit',
                fullWidth && 'w-full'
            )}
        >
            {children}
        </div>
    )
}

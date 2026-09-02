import { cn } from 'lib/utils/css-classes'

export function SceneContent({
    children,
    className,
    fullHeight,
}: {
    children: React.ReactNode
    className?: string
    fullHeight?: boolean
}): JSX.Element {
    return <div className={cn('scene-content flex flex-col gap-y-4', className, fullHeight && 'grow')}>{children}</div>
}

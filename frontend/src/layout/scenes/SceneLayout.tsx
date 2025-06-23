import { cn } from 'lib/utils/css-classes'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
}
export function SceneLayout({ children, className }: SceneLayoutProps): JSX.Element {
    return (
        <div className={cn('flex-1 flex flex-col px-4', className)}>{children}</div>
    )
}

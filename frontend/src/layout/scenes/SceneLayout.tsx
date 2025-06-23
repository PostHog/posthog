import { cn } from 'lib/utils/css-classes'

type SceneLayoutProps = {
    header: React.ReactNode
    children: React.ReactNode
    className?: string
}
export function SceneLayout({ header, children, className }: SceneLayoutProps): JSX.Element {
    return (
        <>
            {header}
            <div className={cn('flex-1 flex flex-col px-4', className)}>{children}</div>
        </>
    )
}

import { cn } from 'lib/utils/css-classes'

export function SceneContent({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return <div className={cn('scene-content flex flex-col gap-y-4 relative', className)}>{children}</div>
}

import { ReactNode } from 'react'

export function WaysToUsePreviewWindow({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="absolute top-4 -right-6 -bottom-6 left-14 overflow-hidden rounded-lg border border-border bg-background shadow-sm transition-transform duration-300 ease-out group-has-[a:hover]/card:-translate-y-0.5 group-has-[a:focus-visible]/card:-translate-y-0.5 motion-reduce:transition-none">
            <div className="mr-6">{children}</div>
        </div>
    )
}

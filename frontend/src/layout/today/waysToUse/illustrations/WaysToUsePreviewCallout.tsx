import { ReactNode } from 'react'

export function WaysToUsePreviewCallout({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="absolute right-8 bottom-4 left-4 flex">
            <div className="flex w-fit max-w-full flex-col gap-0.5 rounded-lg border border-border bg-background px-2.5 py-2 shadow-md transition-transform duration-300 ease-out group-has-[a:hover]/card:-translate-y-1 group-has-[a:focus-visible]/card:-translate-y-1 motion-reduce:transition-none">
                {children}
            </div>
        </div>
    )
}

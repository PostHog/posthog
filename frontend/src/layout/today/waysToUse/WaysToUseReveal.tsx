import { ReactNode } from 'react'

export function WaysToUseReveal({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="translate-y-1 opacity-0 transition duration-200 ease-out group-has-[a:hover]/card:translate-y-0 group-has-[a:hover]/card:opacity-100 group-has-[a:hover]/card:delay-100 group-has-[a:focus-visible]/card:translate-y-0 group-has-[a:focus-visible]/card:opacity-100 group-has-[a:focus-visible]/card:delay-100 motion-reduce:transition-none">
            {children}
        </div>
    )
}

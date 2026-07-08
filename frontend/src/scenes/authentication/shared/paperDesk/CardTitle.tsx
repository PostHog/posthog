import { type ReactNode } from 'react'

export function CardTitle({
    title,
    sub,
    className,
}: {
    title: ReactNode
    sub?: ReactNode
    className?: string
}): JSX.Element {
    return (
        <div className={className ?? 'mb-6'}>
            <h1 className="m-0 text-xl font-bold leading-tight text-center tracking-tight">{title}</h1>
            {sub && <p className="mt-2 mb-0 text-sm text-gray-600 text-center text-pretty">{sub}</p>}
        </div>
    )
}

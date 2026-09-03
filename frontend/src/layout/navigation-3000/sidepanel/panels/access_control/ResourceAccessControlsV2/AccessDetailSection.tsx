import { ReactNode } from 'react'

/** Titled block used by the access detail sections, shared so the Defaults tab can reuse them. */
export function AccessDetailSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div>
                <h3 className="mb-0">{title}</h3>
                {description && <p className="text-secondary text-sm mb-0">{description}</p>}
            </div>
            {children}
        </div>
    )
}

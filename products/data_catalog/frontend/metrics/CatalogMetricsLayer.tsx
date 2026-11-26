import { ReactNode } from 'react'

import { Badge, Heading } from '@posthog/quill'

export interface CatalogMetricsLayerProps {
    title: string
    /** Omit the count when the list did not load. */
    count?: number
    description?: ReactNode
    dataAttr: string
    children: ReactNode
}

export function CatalogMetricsLayer({
    title,
    count,
    description,
    dataAttr,
    children,
}: CatalogMetricsLayerProps): JSX.Element {
    const headingId = `${dataAttr}-heading`
    return (
        <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2" data-attr={dataAttr}>
            <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 id={headingId} className="m-0" />}>
                        {title}
                    </Heading>
                    {count !== undefined && <Badge translate="no">{count}</Badge>}
                </div>
                {description}
            </div>
            {children}
        </section>
    )
}

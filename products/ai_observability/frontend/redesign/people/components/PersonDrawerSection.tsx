import { ReactNode } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { ListErrorState } from '../../lists/components/ListErrorState'
import type { TraceCellLoad } from '../../shared/cellLoads'

const SKELETON_ROWS = 3

export interface PersonDrawerSectionProps<T> {
    title: string
    load: TraceCellLoad<T[]>
    /** What the section says once read with nothing in it. */
    empty: string
    failedTitle: string
    retry: { onClick: () => void; 'data-attr': string }
    renderItem: (item: T) => ReactNode
    footer?: ReactNode
}

function sectionBody<T>({
    load,
    empty,
    failedTitle,
    retry,
    renderItem,
}: Omit<PersonDrawerSectionProps<T>, 'title' | 'footer'>): ReactNode {
    if (load.status === 'loading') {
        return Array.from({ length: SKELETON_ROWS }, (_, index) => <LemonSkeleton key={index} className="h-10" />)
    }
    if (load.status === 'error') {
        return (
            <ListErrorState
                title={failedTitle}
                description="Try again. If it keeps happening, contact support."
                retry={retry}
            />
        )
    }
    if (load.value.length === 0) {
        return <p className="m-0 text-secondary">{empty}</p>
    }
    return <ul className="m-0 flex list-none flex-col gap-1 p-0">{load.value.map(renderItem)}</ul>
}

export function PersonDrawerSection<T>({ title, footer, ...body }: PersonDrawerSectionProps<T>): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0 text-sm font-semibold">{title}</h3>
            {sectionBody(body)}
            {footer}
        </section>
    )
}

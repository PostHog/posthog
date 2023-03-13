import clsx from 'clsx'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useState } from 'react'

export interface AccordionItem {
    key: string | number
    /** Item title. This must be a string for accesibility. */
    title: string
    /** Optional richer form of title, which can be a JSX element. */
    richTitle?: string | JSX.Element
    /** URL within the app. */
    url: string
}

interface SidebarAccordionProps {
    title: string
    items: AccordionItem[]
    loading?: boolean
}

export function SidebarAccordion({ title, items, loading = false }: SidebarAccordionProps): JSX.Element {
    const { push } = useActions(router)

    const [isExpanded, setIsExpanded] = useState(false)

    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isDisabled = isEmpty && !isExpanded

    return (
        <section className={clsx('Accordion', isExpanded && 'Accordion--expanded')} aria-disabled={isDisabled}>
            <div
                className="Accordion__header"
                onClick={isExpanded || items.length > 0 ? () => setIsExpanded(!isExpanded) : undefined}
            >
                {!loading ? <IconChevronRight /> : <Spinner />}
                <h5>
                    {title}
                    {isEmptyDefinitively && (
                        <>
                            {' '}
                            <i>(empty)</i>
                        </>
                    )}
                </h5>
            </div>
            {isExpanded && (
                <div className="Accordion_content">
                    <div className="Accordion_meta">Name</div>
                    <ul className="Accordion_list">
                        {items.map((item) => (
                            <li key={item.key} onClick={() => push(item.url)} title={item.title}>
                                {item.richTitle || item.title}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </section>
    )
}

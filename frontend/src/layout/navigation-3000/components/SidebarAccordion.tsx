import clsx from 'clsx'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Accordion } from '../types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SidebarList } from './SidebarList'

interface SidebarAccordionProps {
    title: Accordion['title']
    items: Accordion['items']
    loadMore: Accordion['loadMore']
    loading: Accordion['loading']
    collapsed: boolean
    toggle: () => void
    activeItemKey: string | number | null
}

export function SidebarAccordion({
    title,
    items,
    activeItemKey,
    collapsed,
    toggle,
    loadMore,
    loading = false,
}: SidebarAccordionProps): JSX.Element {
    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isExpanded = !collapsed && !isEmpty

    return (
        <section
            className={clsx('Accordion', isExpanded && 'Accordion--expanded')}
            aria-busy={loading}
            aria-disabled={isEmpty}
        >
            <div className="Accordion__header" onClick={isExpanded || items.length > 0 ? () => toggle() : undefined}>
                {!loading ? <IconChevronRight /> : <Spinner />}
                <h4>
                    {title}
                    {isEmptyDefinitively && (
                        <>
                            {' '}
                            <i>(empty)</i>
                        </>
                    )}
                </h4>
            </div>
            {isExpanded && (
                <div className="Accordion__content">
                    <SidebarList items={items} activeItemKey={activeItemKey} loadMore={loadMore} />
                </div>
            )}
        </section>
    )
}

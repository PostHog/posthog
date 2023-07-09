import { IconChevronRight } from 'lib/lemon-ui/icons'
import { SidebarCategory } from '../types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SidebarList } from './SidebarList'
import { navigation3000Logic } from '../navigationLogic'
import { useActions, useValues } from 'kea'

interface SidebarAccordionProps {
    category: SidebarCategory
}

export function SidebarAccordion({ category }: SidebarAccordionProps): JSX.Element {
    const { accordionCollapseMapping } = useValues(navigation3000Logic)
    const { toggleAccordion } = useActions(navigation3000Logic)

    const { key, title, items, loading } = category

    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isExpanded = !accordionCollapseMapping[key] && !isEmpty

    return (
        <section className="Accordion" aria-busy={loading} aria-disabled={isEmpty} aria-expanded={isExpanded}>
            <div
                className="Accordion__header"
                onClick={isExpanded || items.length > 0 ? () => toggleAccordion(key) : undefined}
            >
                {loading ? <Spinner /> : <IconChevronRight />}
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
            {isExpanded && <SidebarList category={category} />}
        </section>
    )
}

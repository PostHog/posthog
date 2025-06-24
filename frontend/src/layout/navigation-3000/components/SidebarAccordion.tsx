import { useActions, useValues } from 'kea'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'

import { navigation3000Logic } from '../navigationLogic'
import { SidebarCategory } from '../types'
import { NewItemButton } from './NewItemButton'
import { SidebarList } from './SidebarList'

interface SidebarAccordionProps {
    category: SidebarCategory
}

export function SidebarAccordion({ category }: SidebarAccordionProps): JSX.Element {
    const { accordionCollapseMapping } = useValues(navigation3000Logic)
    const { toggleAccordion } = useActions(navigation3000Logic)

    const { key, items, loading } = category

    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isExpanded = !accordionCollapseMapping[key]

    // If we have an empty component, always display it when empty
    const showEmptyComponent = category.emptyComponentLogic
        ? category.emptyComponentLogic(items)
        : category.emptyComponent && isEmptyDefinitively

    return (
        <section
            className="Accordion"
            aria-busy={loading}
            aria-disabled={isEmpty && !showEmptyComponent}
            aria-expanded={isExpanded}
        >
            <div
                className="Accordion__header"
                onClick={isExpanded || items.length > 0 || showEmptyComponent ? () => toggleAccordion(key) : undefined}
            >
                {loading ? <Spinner /> : <IconChevronRight />}
                <h4>
                    {capitalizeFirstLetter(pluralizeCategory(category.noun))}
                    {isEmptyDefinitively && (
                        <>
                            {' '}
                            <i>(empty)</i>
                        </>
                    )}
                </h4>
                <NewItemButton category={category} />
            </div>
            {isExpanded && !isEmpty && <SidebarList category={category} />}
            {isExpanded && showEmptyComponent && category.emptyComponent}
        </section>
    )
}

export function singularizeCategory(noun: SidebarCategory['noun']): string {
    return Array.isArray(noun) ? noun[0] : noun
}

export function pluralizeCategory(noun: SidebarCategory['noun']): string {
    return Array.isArray(noun) ? noun[1] : `${noun}s`
}

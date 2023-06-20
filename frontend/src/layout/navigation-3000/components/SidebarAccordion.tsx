import { IconChevronRight } from 'lib/lemon-ui/icons'
import { SidebarCategory } from '../types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SidebarList } from './SidebarList'

interface SidebarAccordionPropsBase {
    title: SidebarCategory['title']
    items: SidebarCategory['items']
    remote: SidebarCategory['remote']
    loading: SidebarCategory['loading']
    activeItemKey: string | number | null
}
interface SidebarAccordionPropsStatic extends SidebarAccordionPropsBase {
    collapsed?: never
    toggle?: never
}
interface SidebarAccordionPropsExpandable extends SidebarAccordionPropsBase {
    collapsed: boolean
    toggle: () => void
}
export type SidebarAccordionProps = SidebarAccordionPropsStatic | SidebarAccordionPropsExpandable

export function SidebarAccordion({
    title,
    items,
    activeItemKey,
    collapsed,
    toggle,
    remote,
    loading = false,
}: SidebarAccordionProps): JSX.Element {
    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isExpanded = !toggle || (!collapsed && !isEmpty)

    return (
        <section className="Accordion" aria-busy={loading} aria-disabled={isEmpty} aria-expanded={toggle && isExpanded}>
            {toggle ? (
                <div className="Accordion__header" onClick={isExpanded || items.length > 0 ? toggle : undefined}>
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
            ) : null}
            {isExpanded && <SidebarList items={items} activeItemKey={activeItemKey} remote={remote} />}
        </section>
    )
}

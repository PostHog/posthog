import { Link, TZLabel } from '@posthog/apps-common'
import clsx from 'clsx'
import { isDayjs } from 'lib/dayjs'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useState } from 'react'
import { BasicListItem, ExtendedListItem, ExtraListItemContext } from '../types'

interface SidebarAccordionProps {
    title: string
    items: BasicListItem[] | ExtendedListItem[]
    activeItemKey: BasicListItem['key'] | null
    loading?: boolean
}

export function SidebarAccordion({ title, items, activeItemKey, loading = false }: SidebarAccordionProps): JSX.Element {
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
                    <div className="Accordion__meta">Name</div>
                    <SidebarList items={items} activeItemKey={activeItemKey} />
                </div>
            )}
        </section>
    )
}

interface SidebarListProps {
    items: BasicListItem[] | ExtendedListItem[]
    activeItemKey: BasicListItem['key'] | null
}

export function SidebarList({ items, activeItemKey }: SidebarListProps): JSX.Element {
    return (
        <ul className="SidebarList">
            {items.map((item) => (
                <li
                    key={item.key}
                    title={item.name}
                    className={clsx(
                        'SidebarList__item',
                        item.marker && `SidebarList__item--marker-${item.marker.type}`,
                        item.marker?.status && `SidebarList__item--marker-status-${item.marker.status}`,
                        'summary' in item && 'SidebarList__item--extended'
                    )}
                    aria-current={item.key === activeItemKey ? 'page' : undefined}
                >
                    {' '}
                    <Link to={item.url}>
                        {'summary' in item ? (
                            <>
                                <div className="flex space-between gap-1">
                                    <h5 className="flex-1">{item.name}</h5>
                                    <div>
                                        <ExtraContext data={item.extraContextTop} />
                                    </div>
                                </div>
                                <div className="flex space-between gap-1">
                                    <div className="flex-1 overflow-hidden text-ellipsis">{item.summary}</div>
                                    <div>
                                        <ExtraContext data={item.extraContextBottom} />
                                    </div>
                                </div>
                            </>
                        ) : (
                            <h5>{item.name}</h5>
                        )}
                    </Link>
                </li>
            ))}
        </ul>
    )
}

function ExtraContext({ data }: { data: ExtraListItemContext }): JSX.Element {
    return isDayjs(data) ? <TZLabel time={data} /> : <>{data}</>
}

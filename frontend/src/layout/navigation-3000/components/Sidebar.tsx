import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import React, { useEffect, useState } from 'react'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { navigation3000Logic } from '../navigationLogic'

export function Sidebar(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
    } = useValues(navigation3000Logic)
    const { syncSidebarWidthWithMouseMove, beginResize, endResize } = useActions(navigation3000Logic)
    const { recentInsights, recentInsightsLoading } = useValues(projectHomepageLogic)
    const { loadRecentInsights } = useActions(projectHomepageLogic)

    useEffect(() => {
        loadRecentInsights()
    }, [])

    useEffect(() => {
        if (isResizeInProgress) {
            const onMouseMove = (e: MouseEvent): void => syncSidebarWidthWithMouseMove(e.movementX)
            const onMouseUp = (e: MouseEvent): void => {
                if (e.button === 0) {
                    endResize()
                }
            }
            document.addEventListener('mousemove', onMouseMove)
            document.addEventListener('mouseup', onMouseUp)
            return () => {
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onMouseUp)
            }
        }
    }, [isResizeInProgress, syncSidebarWidthWithMouseMove])

    return (
        <div
            className={clsx(
                'Sidebar3000',
                !isShown && 'Sidebar3000--hidden',
                isResizeInProgress && 'Sidebar3000--resizing',
                overslideDirection && `Sidebar3000--overslide-${overslideDirection}`
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--sidebar-width': `${isShown ? width : 0}px`,
                } as React.CSSProperties
            }
        >
            <div className="Sidebar3000__content">
                <div className="Sidebar3000__header">
                    <h4>{currentTeam?.name}</h4>
                </div>
                <Accordion
                    title="Last viewed insights"
                    items={recentInsights.slice(0, 5).map((insight) => ({
                        key: insight.id,
                        title: insight.name || insight.derived_name || `Insight #${insight.id}`,
                        richTitle: insight.name || <i>{insight.derived_name}</i> || `Insight #${insight.id}`,
                        url: urls.insightView(insight.short_id),
                    }))}
                    loading={recentInsightsLoading}
                />
                <Accordion
                    title="Newly seen persons"
                    items={
                        [
                            /* TODO */
                        ]
                    }
                />
                <Accordion
                    title="Recent recordings"
                    items={
                        [
                            /* TODO */
                        ]
                    }
                />
            </div>
            <div
                className="Sidebar3000__slider"
                onMouseDown={(e) => {
                    if (e.button === 0) {
                        beginResize()
                    }
                }}
            />
        </div>
    )
}

interface AccordionItem {
    key: string | number
    /** Item title. This must be a string for accesibility. */
    title: string
    /** Optional richer form of title, which can be a JSX element. */
    richTitle?: string | JSX.Element
    /** URL within the app. */
    url: string
}

interface AccordionProps {
    title: string
    items: AccordionItem[]
    loading?: boolean
}

function Accordion({ title, items, loading = false }: AccordionProps): JSX.Element {
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

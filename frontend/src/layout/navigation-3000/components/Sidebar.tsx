import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import React, { useEffect } from 'react'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { navigation3000Logic } from '../navigationLogic'
import { KeyboardShortcut } from './KeyboardShortcut'
import { SidebarAccordion } from './SidebarAccordion'

export function Sidebar(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
        isSidebarKeyboardShortcutAcknowledged,
    } = useValues(navigation3000Logic)
    const { beginResize } = useActions(navigation3000Logic)
    const { recentInsights, recentInsightsLoading } = useValues(projectHomepageLogic)
    const { loadRecentInsights } = useActions(projectHomepageLogic)

    useEffect(() => {
        loadRecentInsights()
    }, [])

    return (
        <div
            className={clsx(
                'Sidebar3000',
                isResizeInProgress && 'Sidebar3000--resizing',
                overslideDirection && `Sidebar3000--overslide-${overslideDirection}`
            )}
            aria-hidden={!isShown}
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
                <div className="Sidebar3000__main">
                    <SidebarAccordion
                        title="Last viewed insights"
                        items={recentInsights.slice(0, 5).map((insight) => ({
                            key: insight.id,
                            title: insight.name || insight.derived_name || `Insight #${insight.id}`,
                            richTitle: insight.name || <i>{insight.derived_name}</i> || `Insight #${insight.id}`,
                            url: urls.insightView(insight.short_id),
                        }))}
                        loading={recentInsightsLoading}
                    />
                    <SidebarAccordion
                        title="Newly seen persons"
                        items={
                            [
                                /* TODO */
                            ]
                        }
                    />
                    <SidebarAccordion
                        title="Recent recordings"
                        items={
                            [
                                /* TODO */
                            ]
                        }
                    />
                </div>
                {!isSidebarKeyboardShortcutAcknowledged && <SidebarKeyboardShortcut />}
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

export function SidebarKeyboardShortcut(): JSX.Element {
    const { acknowledgeSidebarKeyboardShortcut } = useActions(navigation3000Logic)

    return (
        <div className="Sidebar3000__hint">
            <span className="truncate">
                <i>Tip:</i> Press <KeyboardShortcut command b /> to toggle this sidebar
            </span>
            <LemonButton icon={<IconClose />} size="small" onClick={() => acknowledgeSidebarKeyboardShortcut()} />
        </div>
    )
}

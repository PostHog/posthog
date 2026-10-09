import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronLeft, IconSidePanel } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

import { IconShowSidebar } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

export function TodayPhoneHeader(): JSX.Element {
    const { sceneBreadcrumbs } = useValues(breadcrumbsLogic)
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { onAiPage, phoneCanGoBack } = useValues(todayShellLogic)
    const { goBackOnPhone, setMobileSidebarOpen } = useActions(todayShellLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const [scrolled, setScrolled] = useState(false)
    const title = [...sceneBreadcrumbs].reverse().find((breadcrumb) => !!breadcrumb.name)?.name

    useEffect(() => {
        const main = document.getElementById('main-content')
        if (!main) {
            return
        }
        const onScroll = (): void => setScrolled(main.scrollTop > 0)
        onScroll()
        main.addEventListener('scroll', onScroll, { passive: true })
        return () => main.removeEventListener('scroll', onScroll)
    }, [title])

    return (
        <header className="TodayPhoneHeader" data-scrolled={scrolled} data-quill>
            {phoneCanGoBack ? (
                <Button size="icon" aria-label="Back" data-attr="today-phone-back" onClick={goBackOnPhone}>
                    <IconChevronLeft />
                </Button>
            ) : (
                <Button
                    size="icon"
                    aria-label="Open sidebar"
                    data-attr="today-phone-sidebar"
                    onClick={() => setMobileSidebarOpen(true)}
                >
                    <IconShowSidebar />
                </Button>
            )}
            <h2 className="m-0 min-w-0 flex-1 truncate text-base font-bold text-foreground">{title}</h2>
            {!onAiPage && (
                <Button
                    size="icon"
                    aria-label="Open context panel"
                    data-attr="today-phone-context-panel"
                    onClick={() => openSidePanel(scenePanelIsPresent ? SidePanelTab.Info : SidePanelTab.Max)}
                >
                    <IconSidePanel />
                </Button>
            )}
        </header>
    )
}

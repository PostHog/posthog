import './Bets.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconGear, IconHome, IconList, IconPlus } from '@posthog/icons'
import { Button, MenuLabel, Text, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { TodayPaneRow } from '~/layout/today/TodayPaneRow'
import { TodayPaneSearchList } from '~/layout/today/TodayPaneSearchList'

import { BetsSidebarPreviewCard } from './components/BetsSidebarPreviewCard'
import { BetsSidebarRow } from './components/BetsSidebarRow'
import { BetsSidebarSkeleton } from './components/BetsSidebarSkeleton'
import { betsLogic } from './logics/betsLogic'
import { betsSidebarPreviewLogic } from './logics/betsSidebarPreviewLogic'

export const scene: SceneExport = { component: BetsSidebar }

export function BetsSidebar(): JSX.Element {
    const [search, setSearch] = useState('')
    const { location } = useValues(router)
    const { overview, error, recentBets: allRecentBets } = useValues(betsLogic)
    const { loadOverview } = useActions(betsLogic)
    const { closePreview } = useActions(betsSidebarPreviewLogic)
    const pathname = removeProjectIdIfPresent(location.pathname)
    const recentBets = allRecentBets
        .filter((bet) => bet.title.toLowerCase().includes(search.toLowerCase()))
        .slice(0, 12)
    const loading = !overview && !error
    const canEdit = overview?.can_edit ?? false
    const showRecent = loading || !!error || canEdit || recentBets.length > 0

    const recentBody = loading ? (
        <BetsSidebarSkeleton />
    ) : !overview ? (
        <div className="flex flex-col items-start gap-2 px-2 py-1">
            <Text size="xs" variant="muted">
                Bets didn’t load.
            </Text>
            <Button variant="outline" size="sm" onClick={() => loadOverview()} data-attr="bets-sidebar-retry">
                Try again
            </Button>
        </div>
    ) : recentBets.length === 0 ? (
        <Text size="xs" variant="muted" className="px-2 py-1">
            {search ? 'No matches' : 'Bets you make show up here.'}
        </Text>
    ) : (
        recentBets.map((bet) => (
            <BetsSidebarRow
                key={bet.id}
                bet={bet}
                to={urls.bet(bet.id)}
                active={[urls.bet(bet.id), urls.betEdit(bet.id)].includes(pathname)}
            />
        ))
    )

    return (
        <TooltipProvider>
            <div className="TodayPane" data-quill onScrollCapture={closePreview}>
                <BetsSidebarPreviewCard bets={recentBets}>
                    <TodayPaneSearchList
                        query={search}
                        onQueryChange={setSearch}
                        searchLabel="Search bets"
                        dataAttr="bets-search"
                    >
                        <TodayPaneRow
                            value="overview"
                            label="Overview"
                            icon={<IconHome />}
                            to={urls.bets()}
                            active={pathname === urls.bets()}
                        />
                        <TodayPaneRow
                            value="all"
                            label="All bets"
                            icon={<IconList />}
                            to={urls.betsAll()}
                            active={pathname === urls.betsAll()}
                        />
                        <TodayPaneRow
                            value="settings"
                            label="Settings"
                            icon={<IconGear />}
                            to={urls.betsSettings()}
                            active={pathname === urls.betsSettings()}
                        />
                        {showRecent && (
                            <section aria-label="Recent bets" className="mt-2 flex flex-col gap-px">
                                <div className="flex h-7 items-center gap-1">
                                    <MenuLabel className="min-w-0 flex-1 truncate py-1">Recent bets</MenuLabel>
                                    {canEdit && (
                                        <Tooltip>
                                            <TooltipTrigger
                                                delay={0}
                                                render={
                                                    <Button
                                                        size="icon"
                                                        render={<LinkPrimitive to={urls.betsNew()} />}
                                                        className="text-muted-foreground"
                                                        aria-label="New bet"
                                                        data-attr="bets-sidebar-new-bet"
                                                    />
                                                }
                                            >
                                                <IconPlus />
                                            </TooltipTrigger>
                                            <TooltipContent>New bet</TooltipContent>
                                        </Tooltip>
                                    )}
                                </div>
                                {recentBody}
                            </section>
                        )}
                    </TodayPaneSearchList>
                </BetsSidebarPreviewCard>
            </div>
        </TooltipProvider>
    )
}

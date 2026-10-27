import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconGear, IconHome, IconList, IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { TodayPaneGroupLabel } from '~/layout/today/TodayPaneGroupLabel'
import { TodayPaneRow } from '~/layout/today/TodayPaneRow'
import { TodayPaneSearchList } from '~/layout/today/TodayPaneSearchList'

import { BetsSidebarRow } from './components/BetsSidebarRow'
import { betsLogic } from './logics/betsLogic'

export const scene: SceneExport = { component: BetsSidebar }

export function BetsSidebar(): JSX.Element {
    const [search, setSearch] = useState('')
    const { location } = useValues(router)
    const { overview, recentBets: allRecentBets } = useValues(betsLogic)
    const pathname = removeProjectIdIfPresent(location.pathname)
    const recentBets = allRecentBets
        .filter((bet) => bet.title.toLowerCase().includes(search.toLowerCase()))
        .slice(0, 12)
    return (
        <div className="TodayPane" data-quill>
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
                {recentBets.length > 0 && (
                    <>
                        <TodayPaneGroupLabel first={false}>Recent bets</TodayPaneGroupLabel>
                        {recentBets.map((bet) => (
                            <BetsSidebarRow
                                key={bet.id}
                                bet={bet}
                                to={urls.bet(bet.id)}
                                active={[urls.bet(bet.id), urls.betEdit(bet.id)].includes(pathname)}
                            />
                        ))}
                    </>
                )}
            </TodayPaneSearchList>
            {overview?.can_edit && (
                <div className="pt-3">
                    <Button variant="outline" className="w-full" render={<LinkPrimitive to={urls.betsNew()} />}>
                        <IconPlus /> New bet
                    </Button>
                </div>
            )}
        </div>
    )
}

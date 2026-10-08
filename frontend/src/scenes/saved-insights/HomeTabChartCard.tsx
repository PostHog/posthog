import './HomeTabChartCard.scss'

import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'

import {
    homeTabChartInsightId,
    homeTabDataCollectionId,
} from 'products/product_analytics/frontend/insights/home/homeTabQueryKeys'

import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabExploreUrl, type HomeTabChartOption } from './homeTabDefaultTiles'

interface HomeTabChartCardProps {
    option: HomeTabChartOption
    size: 'primary' | 'supporting' | 'ranking'
    control?: ReactNode
    source?: string
}

export function HomeTabChartCard({ option, size, control, source }: HomeTabChartCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    return (
        <LemonCard hoverEffect={false} className="HomeTabChartCard flex min-w-0 flex-col overflow-hidden p-0">
            <div className="HomeTabChartCard__header border-b border-primary px-4 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <div className="flex min-w-0 items-center gap-1">
                        <h3 className="m-0 truncate text-base font-semibold">{option.title}</h3>
                        {source && (
                            <Tooltip title={`Based on ${source}`}>
                                <IconInfo className="shrink-0 text-secondary" />
                            </Tooltip>
                        )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        {control}
                        <LemonButton
                            type="tertiary"
                            size="small"
                            to={getHomeTabExploreUrl(option.query)}
                            data-attr={`home-tab-explore-${option.key}`}
                        >
                            Explore
                        </LemonButton>
                    </div>
                </div>
                <Tooltip title={option.description}>
                    <p className="m-0 mt-0.5 text-xs text-secondary">{option.description}</p>
                </Tooltip>
            </div>
            <div
                className={`HomeTabDefaultChart HomeTabChartCard__visualization HomeTabChartCard__visualization--${size}`}
            >
                <Query
                    key={currentTeamId}
                    query={option.query}
                    readOnly
                    uniqueKey={`HomeTab.${currentTeamId}.${option.key}`}
                    context={{
                        insightProps: {
                            dashboardItemId: homeTabChartInsightId(currentTeamId, option.key),
                            dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
                            query: option.query,
                        },
                    }}
                    attachTo={homeTabDefaultLogic}
                />
            </div>
        </LemonCard>
    )
}

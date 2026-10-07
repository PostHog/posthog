import { useValues } from 'kea'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { formatItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import type { TrendsQueryResponse } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabStatValue, type HomeTabStatQuery } from './homeTabDefaultTiles'

interface HomeTabStatTileProps {
    stat: HomeTabStatQuery
    compare: boolean
    selected: boolean
    onSelect: () => void
}

export function HomeTabStatTile({ stat, compare, selected, onSelect }: HomeTabStatTileProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const key = `HomeTabStatTile.${currentTeamId}.${stat.key}`
    const logic = dataNodeLogic({ query: stat.query, key, dataNodeCollectionId: key })
    useAttachedLogic(logic, homeTabDefaultLogic)
    const { response, responseError, responseLoading } = useValues(logic)
    const loading = responseLoading || (!response && !responseError)

    const results = (response as TrendsQueryResponse | undefined)?.results ?? (response as { result?: unknown })?.result
    const current = (results as TrendResult[] | undefined)?.[0]
    const previous = compare ? (results as TrendResult[] | undefined)?.[1] : undefined
    const value = getHomeTabStatValue(stat, current)
    const previousValue = getHomeTabStatValue(stat, previous)
    const changeFromPreviousPct =
        value != null && previousValue != null && previousValue !== 0
            ? ((value - previousValue) / Math.abs(previousValue)) * 100
            : undefined

    const label =
        stat.description || stat.key === 'session_duration' ? (
            <Tooltip title={stat.description ?? 'Average duration of sessions with a page or screen view.'}>
                {stat.title}
            </Tooltip>
        ) : (
            stat.title
        )

    const subtitle = !compare
        ? 'For selected period'
        : previousValue == null
          ? 'No previous period data'
          : `vs. ${formatItem(previousValue, stat.kind)} prior`

    return (
        <AnalyticsMetricCard
            className="h-full w-full"
            title={label}
            ariaLabel={stat.title}
            onClick={onSelect}
            selected={selected}
            loading={loading}
            error={responseError ? 'Could not load' : undefined}
            dataAttr={`home-tab-metric-${stat.key}`}
            value={value ?? undefined}
            showChange={compare}
            change={changeFromPreviousPct ? { value: changeFromPreviousPct } : null}
            goodDirection="up"
            formatValue={(statValue) => formatItem(statValue, stat.kind)}
            subtitle={<span translate="no">{subtitle}</span>}
        />
    )
}

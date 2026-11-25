import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { ProposedMetricApi } from '../generated/api.schemas'
import { surfaceSourceLabel, surfaceSourceUsage } from '../proposedSources'

export function ProposedMetricSources({
    metric,
}: {
    metric: Pick<ProposedMetricApi, 'charts' | 'other_charts' | 'surfaces' | 'agents'>
}): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col gap-1 py-1 pl-0 text-xs">
            {metric.charts.map((chart) => (
                <li key={`${chart.insight_short_id}-${chart.dashboard_id}`}>
                    Used in{' '}
                    <Link to={urls.insightView(chart.insight_short_id as InsightShortId)}>{chart.insight_name}</Link>
                    {chart.dashboard_id !== null && (
                        <>
                            {' '}
                            on <Link to={urls.dashboard(chart.dashboard_id)}>{chart.dashboard_name}</Link>
                        </>
                    )}
                    <span className="text-secondary"> ({pluralize(chart.people, 'person', 'people')})</span>
                </li>
            ))}
            {metric.other_charts > 0 && (
                <li className="text-secondary">and {pluralize(metric.other_charts, 'more chart')}</li>
            )}
            {metric.surfaces.map((surface) => (
                <li key={surface.product}>
                    {surfaceSourceLabel(surface)}
                    <span className="text-secondary"> ({surfaceSourceUsage(surface)})</span>
                </li>
            ))}
            {metric.agents && (
                <li>
                    {pluralize(metric.agents.people, 'person', 'people')} wrote this in{' '}
                    {pluralize(metric.agents.sessions, 'agent session')}
                </li>
            )}
        </ul>
    )
}

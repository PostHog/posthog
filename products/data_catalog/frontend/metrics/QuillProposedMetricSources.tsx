import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { ProposedMetricApi } from '../generated/api.schemas'
import { surfaceSourceLabel, surfaceSourceUsage } from '../proposedSources'

function SourceLink({ to, children }: { to: string; children: string }): JSX.Element {
    return (
        <Button variant="link-foreground" size="inline" nativeButton={false} render={<LinkPrimitive to={to} />}>
            {children}
        </Button>
    )
}

function Muted({ children }: { children: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />}>
            {children}
        </Text>
    )
}

export function QuillProposedMetricSources({
    metric,
}: {
    metric: Pick<ProposedMetricApi, 'charts' | 'other_charts' | 'surfaces' | 'agents'>
}): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col gap-1 py-1 pl-0 text-xs">
            {metric.charts.map((chart) => (
                <li key={`${chart.insight_short_id}-${chart.dashboard_id}`} className="flex flex-wrap gap-x-1">
                    Used in
                    <SourceLink to={urls.insightView(chart.insight_short_id as InsightShortId)}>
                        {chart.insight_name}
                    </SourceLink>
                    {chart.dashboard_id !== null && (
                        <>
                            on
                            <SourceLink to={urls.dashboard(chart.dashboard_id)}>
                                {chart.dashboard_name ?? ''}
                            </SourceLink>
                        </>
                    )}
                    <Muted>{`(${pluralize(chart.people, 'person', 'people')})`}</Muted>
                </li>
            ))}
            {metric.other_charts > 0 && (
                <li>
                    <Muted>{`and ${pluralize(metric.other_charts, 'more chart')}`}</Muted>
                </li>
            )}
            {metric.surfaces.map((surface) => (
                <li key={surface.product} className="flex flex-wrap gap-x-1">
                    {surfaceSourceLabel(surface)}
                    <Muted>{`(${surfaceSourceUsage(surface)})`}</Muted>
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

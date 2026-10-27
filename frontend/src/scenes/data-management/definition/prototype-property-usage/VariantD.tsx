// PROTOTYPE — Variant D: a dependency outline. Everything that refers to the property, grouped by surface,
// with an impact summary beside it. Answers "what breaks if I change this?" rather than "how busy is it?".
import { IconDashboard, IconFlag, IconGraph, IconPeople, IconTestTube } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PropertyUsage, ROLE_LABELS, UsageInsight } from './propertyUsageMock'
import { SourceTag } from './PrototypeBits'

export const VARIANT_D_NAME = 'Dependency outline'

function InsightLine({ insight }: { insight: UsageInsight }): JSX.Element {
    return (
        <li className="flex flex-wrap items-center gap-2 py-0.5">
            <IconGraph className="text-secondary" />
            <Link to={urls.insightView(insight.short_id as any)}>{insight.name}</Link>
            {insight.roles.map((role) => (
                <LemonTag key={role} size="small">
                    {ROLE_LABELS[role]}
                </LemonTag>
            ))}
            <span className={`text-xs ${insight.views30d ? 'text-secondary' : 'text-danger'}`}>
                {insight.views30d ? `${insight.views30d.toLocaleString()} views` : 'not viewed in 30 days'}
            </span>
        </li>
    )
}

export function VariantD({ usage }: { usage: PropertyUsage }): JSX.Element {
    const byDashboard = new Map<string, UsageInsight[]>()
    for (const insight of usage.insights) {
        for (const dashboard of insight.dashboards) {
            byDashboard.set(dashboard, [...(byDashboard.get(dashboard) ?? []), insight])
        }
    }
    const loose = usage.insights.filter((i) => i.dashboards.length === 0)
    const staleInsights = usage.insights.filter((i) => i.views30d === 0).length
    const nothing = usage.insights.length === 0 && usage.otherReferences.length === 0

    return (
        <SceneSection title="Referenced by" description="Everything in this project that refers to this property.">
            <div className="flex flex-wrap gap-6 items-start">
                <div className="flex-[2] min-w-80">
                    {nothing ? (
                        <div className="text-secondary italic">Nothing refers to this property.</div>
                    ) : (
                        <ul className="list-none m-0 p-0 flex flex-col gap-3">
                            {[...byDashboard.entries()].map(([dashboard, insights]) => (
                                <li key={dashboard}>
                                    <div className="flex items-center gap-2 font-semibold">
                                        <IconDashboard /> {dashboard}
                                        <SourceTag source="new" />
                                    </div>
                                    <ul className="list-none m-0 pl-6 border-l ml-2">
                                        {insights.map((insight) => (
                                            <InsightLine key={insight.short_id} insight={insight} />
                                        ))}
                                    </ul>
                                </li>
                            ))}
                            {loose.length > 0 && (
                                <li>
                                    <div className="flex items-center gap-2 font-semibold">
                                        <IconGraph /> Not on a dashboard
                                        <SourceTag source="pr" />
                                    </div>
                                    <ul className="list-none m-0 pl-6 border-l ml-2">
                                        {loose.map((insight) => (
                                            <InsightLine key={insight.short_id} insight={insight} />
                                        ))}
                                    </ul>
                                </li>
                            )}
                            {usage.otherReferences.length > 0 && (
                                <li>
                                    <div className="flex items-center gap-2 font-semibold">
                                        <IconFlag /> Flags, cohorts, and experiments
                                        <SourceTag source="new" />
                                    </div>
                                    <ul className="list-none m-0 pl-6 border-l ml-2">
                                        {usage.otherReferences.map((ref) => (
                                            <li key={ref.name} className="flex flex-wrap items-center gap-2 py-0.5">
                                                {ref.kind === 'Cohort' ? (
                                                    <IconPeople className="text-secondary" />
                                                ) : ref.kind === 'Experiment' ? (
                                                    <IconTestTube className="text-secondary" />
                                                ) : (
                                                    <IconFlag className="text-secondary" />
                                                )}
                                                <span>{ref.name}</span>
                                                <LemonTag size="small" type={ref.active ? 'success' : 'muted'}>
                                                    {ref.active ? 'Active' : 'Inactive'}
                                                </LemonTag>
                                                <span className="text-xs text-secondary">{ref.kind}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </li>
                            )}
                        </ul>
                    )}
                </div>

                <div className="flex-1 min-w-60 border rounded p-3 bg-surface-secondary flex flex-col gap-2">
                    <div className="font-semibold">If you rename or hide this property</div>
                    <ul className="m-0 pl-4 flex flex-col gap-1 text-sm">
                        <li>
                            <b>{byDashboard.size}</b> dashboard{byDashboard.size === 1 ? '' : 's'} and{' '}
                            <b>{usage.insights.length}</b> insight{usage.insights.length === 1 ? '' : 's'} stop matching
                            {staleInsights > 0 && ` (${staleInsights} not viewed in 30 days)`}
                        </li>
                        <li>
                            <b>{usage.otherReferences.filter((r) => r.active).length}</b> active flag, cohort or
                            experiment conditions change
                        </li>
                        <li>
                            <b>{usage.queries30d.toLocaleString()}</b> queries a month were using it{' '}
                            <SourceTag source="pr" />
                        </li>
                    </ul>
                    {usage.seenOnEvents.length > 0 && (
                        <div className="text-xs text-secondary flex flex-wrap gap-1 items-center">
                            Sent on
                            {usage.seenOnEvents.map((e) => (
                                <LemonTag key={e.name} size="small" className="font-mono">
                                    {e.name} {Math.round(e.share * 100)}%
                                </LemonTag>
                            ))}
                            <SourceTag source="new" />
                        </div>
                    )}
                </div>
            </div>
        </SceneSection>
    )
}

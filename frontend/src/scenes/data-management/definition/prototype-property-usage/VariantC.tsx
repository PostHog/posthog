// PROTOTYPE — Variant C: activity first. A full-width daily chart, then a feed of who used it through what.
import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PropertyUsage, ROLE_LABELS } from './propertyUsageMock'
import { DailyBars, SourceTag } from './PrototypeBits'

export const VARIANT_C_NAME = 'Activity timeline'

export function VariantC({ usage }: { usage: PropertyUsage }): JSX.Element {
    const peak = Math.max(...usage.daily)
    const activeDays = usage.daily.filter(Boolean).length
    // Mock pairing of people to insights: in reality this needs app_metrics2 grouped by user and insight
    const feed = usage.insights
        .filter((i) => i.lastViewedAt)
        .map((insight) => ({
            insight,
            person: usage.people.find((p) => p.first_name === insight.createdBy) ?? usage.people[0],
        }))
        .sort((a, b) => (b.insight.lastViewedAt ?? '').localeCompare(a.insight.lastViewedAt ?? ''))

    return (
        <SceneSection
            title={
                <span className="flex items-center gap-2">
                    Query activity <SourceTag source="new" />
                </span>
            }
            description={
                usage.lastQueriedAt ? (
                    <>
                        Last queried <TZLabel time={usage.lastQueriedAt} />. Queried on {activeDays} of the last 30
                        days.
                    </>
                ) : (
                    'Not queried in the last 30 days.'
                )
            }
        >
            <div className="border rounded p-3 bg-surface-primary">
                <div className="flex justify-between text-xs text-secondary mb-1">
                    <span>{usage.queries30d.toLocaleString()} queries in 30 days</span>
                    <span>Peak {peak.toLocaleString()} a day</span>
                </div>
                <DailyBars daily={usage.daily} height={96} />
                <div className="flex justify-between text-xs text-secondary mt-1">
                    <span>30 days ago</span>
                    <span>Today</span>
                </div>
            </div>

            {feed.length === 0 ? (
                <div className="text-secondary italic">
                    No saved insight has used this property. Ad hoc queries count toward the chart but leave no trail
                    here.
                </div>
            ) : (
                <ol className="list-none m-0 p-0 border-l-2 ml-3 flex flex-col gap-3">
                    {feed.map(({ insight, person }) => (
                        <li key={insight.short_id} className="relative pl-5">
                            <span className="absolute -left-[7px] top-1.5 w-3 h-3 rounded-full bg-accent" />
                            <div className="flex flex-wrap items-center gap-2">
                                {person && <ProfilePicture user={person} size="sm" />}
                                <span>
                                    <b>{person?.first_name ?? 'Someone'}</b> viewed{' '}
                                    <Link to={urls.insightView(insight.short_id as any)}>{insight.name}</Link>
                                </span>
                                <span className="text-secondary text-xs">
                                    <TZLabel time={insight.lastViewedAt!} />
                                </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-1 mt-1 text-xs text-secondary">
                                {insight.roles.map((role) => (
                                    <LemonTag key={role} size="small">
                                        {ROLE_LABELS[role]}
                                    </LemonTag>
                                ))}
                                <span>
                                    {insight.views30d.toLocaleString()} views in 30 days
                                    {insight.dashboards.length > 0 && ` · on ${insight.dashboards.join(', ')}`}
                                </span>
                            </div>
                        </li>
                    ))}
                </ol>
            )}
        </SceneSection>
    )
}

// PROTOTYPE — Variant A: stat tiles over tabbed detail tables. The familiar "analytics page" shape.
import { useState } from 'react'

import { LemonTable, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PropertyUsage, ROLE_LABELS, UsageInsight, UsagePerson } from './propertyUsageMock'
import { DailyBars, SourceTag } from './PrototypeBits'

export const VARIANT_A_NAME = 'Stat tiles and tabs'

function Tile({
    label,
    value,
    sub,
    source,
    children,
}: {
    label: string
    value: string
    sub?: string
    source: 'pr' | 'new'
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 flex-1 basis-40 min-w-40 border rounded p-3 bg-surface-primary">
            <div className="flex items-center justify-between gap-2 text-xs text-secondary">
                <span>{label}</span>
                <SourceTag source={source} />
            </div>
            <div className="text-2xl font-semibold">{value}</div>
            {sub && <div className="text-xs text-secondary">{sub}</div>}
            {children}
        </div>
    )
}

export function VariantA({ usage }: { usage: PropertyUsage }): JSX.Element {
    const [tab, setTab] = useState<'insights' | 'people' | 'elsewhere'>('insights')
    const change = usage.queriesPrior30d ? (usage.queries30d - usage.queriesPrior30d) / usage.queriesPrior30d : null
    const dashboards = new Set(usage.insights.flatMap((i) => i.dashboards))

    return (
        <SceneSection title="Usage" description="How often this property is queried, and where, in the last 30 days.">
            <div className="flex flex-wrap gap-2">
                <Tile
                    label="Queries"
                    value={usage.queries30d.toLocaleString()}
                    sub={
                        change === null
                            ? 'No queries in the 30 days before'
                            : `${change >= 0 ? '+' : ''}${Math.round(change * 100)}% vs the 30 days before`
                    }
                    source="pr"
                >
                    <DailyBars daily={usage.daily} height={28} />
                </Tile>
                <Tile
                    label="People querying"
                    value={usage.people.length.toLocaleString()}
                    sub={usage.people[0] ? `Most by ${usage.people[0].first_name}` : 'Nobody'}
                    source="new"
                />
                <Tile
                    label="Saved insights"
                    value={usage.insights.length.toLocaleString()}
                    sub={`On ${dashboards.size} dashboard${dashboards.size === 1 ? '' : 's'}`}
                    source="pr"
                />
                <Tile
                    label="Flags, cohorts, experiments"
                    value={usage.otherReferences.length.toLocaleString()}
                    sub={`${usage.otherReferences.filter((r) => r.active).length} active`}
                    source="new"
                />
            </div>

            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    {
                        key: 'insights',
                        label: `Insights (${usage.insights.length})`,
                        content: (
                            <LemonTable<UsageInsight>
                                dataSource={usage.insights}
                                rowKey="short_id"
                                emptyState="No saved insight uses this property"
                                columns={[
                                    {
                                        title: 'Name',
                                        key: 'name',
                                        render: (_, insight) => (
                                            <LemonTableLink
                                                to={urls.insightView(insight.short_id as any)}
                                                title={insight.name}
                                                description={insight.kind}
                                            />
                                        ),
                                    },
                                    {
                                        title: 'Used as',
                                        key: 'roles',
                                        render: (_, insight) => (
                                            <div className="flex flex-wrap gap-1">
                                                {insight.roles.map((role) => (
                                                    <LemonTag key={role}>{ROLE_LABELS[role]}</LemonTag>
                                                ))}
                                            </div>
                                        ),
                                    },
                                    {
                                        title: 'Views (30d)',
                                        key: 'views',
                                        align: 'right',
                                        sorter: (a, b) => a.views30d - b.views30d,
                                        render: (_, insight) => insight.views30d.toLocaleString(),
                                    },
                                    {
                                        title: 'Last viewed',
                                        key: 'last',
                                        render: (_, insight) =>
                                            insight.lastViewedAt ? <TZLabel time={insight.lastViewedAt} /> : '-',
                                    },
                                    {
                                        title: 'Dashboards',
                                        key: 'dashboards',
                                        render: (_, insight) => insight.dashboards.join(', ') || '-',
                                    },
                                ]}
                            />
                        ),
                    },
                    {
                        key: 'people',
                        label: `People (${usage.people.length})`,
                        content: (
                            <LemonTable<UsagePerson>
                                dataSource={usage.people}
                                rowKey="email"
                                emptyState="Nobody queried this property in the last 30 days"
                                columns={[
                                    {
                                        title: 'Person',
                                        key: 'person',
                                        render: (_, person) => <ProfilePicture user={person} size="md" showName />,
                                    },
                                    {
                                        title: 'Queries (30d)',
                                        key: 'queries',
                                        align: 'right',
                                        render: (_, person) => person.queries.toLocaleString(),
                                    },
                                    {
                                        title: 'Last queried',
                                        key: 'last',
                                        render: (_, person) => <TZLabel time={person.lastQueriedAt} />,
                                    },
                                ]}
                            />
                        ),
                    },
                    {
                        key: 'elsewhere',
                        label: `Elsewhere (${usage.otherReferences.length})`,
                        content: (
                            <LemonTable
                                dataSource={usage.otherReferences}
                                rowKey="name"
                                emptyState="No feature flag, cohort, experiment or survey uses this property"
                                columns={[
                                    { title: 'Type', key: 'kind', dataIndex: 'kind' },
                                    { title: 'Name', key: 'name', dataIndex: 'name' },
                                    {
                                        title: 'Status',
                                        key: 'active',
                                        render: (_, ref) => (
                                            <LemonTag type={ref.active ? 'success' : 'muted'}>
                                                {ref.active ? 'Active' : 'Inactive'}
                                            </LemonTag>
                                        ),
                                    },
                                ]}
                            />
                        ),
                    },
                ]}
            />
        </SceneSection>
    )
}

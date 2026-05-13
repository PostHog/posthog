import { useValues } from 'kea'

import { LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { csmHudSceneLogic, FleetRow } from '../logics/csmHudSceneLogic'
import { missingProducts, planType, tier } from '../utils/account'
import { attentionScores } from '../utils/attention'
import { formatMoneyCompact } from '../utils/format'
import { ProjectionRow } from '../utils/projection'

interface ExpansionRow {
    account: FleetRow
    score: number
    reasons: string[]
    plan: 'Annual' | 'Monthly'
    accountTier: ReturnType<typeof tier>
    missing: string[]
    arr: number | null
}

function buildRows(fleet: FleetRow[], projection: Record<string, ProjectionRow>): ExpansionRow[] {
    return fleet
        .map((account) => {
            const scores = attentionScores(account, projection[account.externalId] ?? null)
            return {
                account,
                score: scores.expand,
                reasons: scores.expandReasons,
                plan: planType(account),
                accountTier: tier(account),
                missing: missingProducts(account),
                arr: projection[account.externalId]?.arrDiscounted ?? null,
            }
        })
        .filter((r) => r.score > 0)
        .sort((a, b) => b.score - a.score)
}

function tagsFor(row: ExpansionRow): string[] {
    const tags: string[] = []
    if (row.plan === 'Monthly' && (row.arr ?? 0) >= 18000) {
        tags.push('annual-ready')
    }
    if (row.missing.length >= 2) {
        tags.push('cross-sell')
    } else if (row.missing.length === 1) {
        tags.push('upsell')
    }
    if (row.accountTier === 'Enterprise' || row.accountTier === 'Teams') {
        tags.push('strategic')
    }
    return tags
}

export function ExpansionTab(): JSX.Element {
    const { fleet, projection } = useValues(csmHudSceneLogic)
    const rows = buildRows(fleet, projection)
    const tagCounts: Record<string, number> = {}
    for (const r of rows) {
        for (const t of tagsFor(r)) {
            tagCounts[t] = (tagCounts[t] ?? 0) + 1
        }
    }
    return (
        <div className="space-y-4">
            <div className="text-muted text-sm flex gap-3 flex-wrap">
                <span>{rows.length} expansion candidates</span>
                {Object.entries(tagCounts).map(([tag, n]) => (
                    <span key={tag}>
                        {tag}: {n}
                    </span>
                ))}
            </div>
            {rows.length === 0 ? (
                <div className="text-muted py-8 text-center">
                    No expansion candidates yet — needs healthy accounts with positive MoM and forecast data.
                </div>
            ) : (
                <LemonTable<ExpansionRow>
                    dataSource={rows}
                    rowKey={(r) => r.account.id}
                    columns={[
                        {
                            title: 'Account',
                            key: 'name',
                            render: (_, r) => (
                                <Link to={urls.csmHudCustomer(r.account.externalId)} className="font-medium">
                                    {r.account.name}
                                </Link>
                            ),
                            sorter: (a, b) => a.account.name.localeCompare(b.account.name),
                        },
                        {
                            title: 'Score',
                            key: 'score',
                            align: 'right',
                            render: (_, r) => (
                                <Tooltip title={r.reasons.length ? r.reasons.join(' · ') : 'no reasons'}>
                                    <span>{r.score.toFixed(1)}</span>
                                </Tooltip>
                            ),
                            sorter: (a, b) => a.score - b.score,
                        },
                        {
                            title: 'Tags',
                            key: 'tags',
                            render: (_, r) => (
                                <div className="flex gap-1 flex-wrap">
                                    {tagsFor(r).map((t) => (
                                        <LemonTag key={t}>{t}</LemonTag>
                                    ))}
                                </div>
                            ),
                        },
                        {
                            title: 'Plan',
                            key: 'plan',
                            render: (_, r) => r.plan,
                        },
                        {
                            title: 'Tier',
                            key: 'tier',
                            render: (_, r) => r.accountTier ?? '—',
                        },
                        {
                            title: 'Missing',
                            key: 'missing',
                            render: (_, r) => (r.missing.length === 0 ? '—' : r.missing.join(', ')),
                        },
                        {
                            title: 'ARR',
                            key: 'arr',
                            align: 'right',
                            render: (_, r) => formatMoneyCompact(r.arr),
                            sorter: (a, b) => (a.arr ?? 0) - (b.arr ?? 0),
                        },
                    ]}
                />
            )}
        </div>
    )
}

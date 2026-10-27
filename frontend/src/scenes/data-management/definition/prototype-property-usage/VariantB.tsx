// PROTOTYPE — Variant B: decision first. A verdict for taxonomy cleanup, the evidence behind it, then actions.
import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, lemonToast } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropertyUsage, ROLE_LABELS } from './propertyUsageMock'
import { SourceTag } from './PrototypeBits'

export const VARIANT_B_NAME = 'Cleanup verdict'

type Verdict = 'load-bearing' | 'fading' | 'unused'

function getVerdict(usage: PropertyUsage): Verdict {
    const activeRefs = usage.otherReferences.filter((r) => r.active).length
    if (usage.queries30d === 0 && usage.insights.length === 0 && activeRefs === 0) {
        return 'unused'
    }
    if (usage.queries30d < 100 && activeRefs === 0) {
        return 'fading'
    }
    return 'load-bearing'
}

const VERDICTS: Record<Verdict, { title: string; body: string; className: string; icon: JSX.Element }> = {
    'load-bearing': {
        title: 'Load-bearing',
        body: 'People query this property every week, and active features depend on it. Rename or hide it with care.',
        className: 'border-success bg-success-highlight',
        icon: <IconCheck className="text-success text-2xl" />,
    },
    fading: {
        title: 'Fading',
        body: 'A few queries still use this property, but use is dropping. Check with the people below before you hide it.',
        className: 'border-warning bg-warning-highlight',
        icon: <IconWarning className="text-warning text-2xl" />,
    },
    unused: {
        title: 'Safe to hide',
        body: 'Nothing queried this property in 30 days, and no insight, flag, or cohort refers to it.',
        className: 'border-danger bg-danger-highlight',
        icon: <IconX className="text-danger text-2xl" />,
    },
}

function Check({
    ok,
    children,
    source,
}: {
    ok: boolean
    children: React.ReactNode
    source: 'pr' | 'new'
}): JSX.Element {
    return (
        <li className="flex items-start gap-2">
            {ok ? (
                <IconCheck className="text-success mt-0.5 shrink-0" />
            ) : (
                <IconX className="text-muted mt-0.5 shrink-0" />
            )}
            <span className="flex-1">{children}</span>
            <SourceTag source={source} />
        </li>
    )
}

export function VariantB({ usage }: { usage: PropertyUsage }): JSX.Element {
    const verdict = getVerdict(usage)
    const v = VERDICTS[verdict]
    const activeRefs = usage.otherReferences.filter((r) => r.active)
    const dashboards = new Set(usage.insights.flatMap((i) => i.dashboards))
    const trendDown = usage.queriesPrior30d > 0 && usage.queries30d < usage.queriesPrior30d * 0.5

    const stub = (what: string): void => {
        lemonToast.info(`Prototype: would ${what}`)
    }

    return (
        <div className="flex flex-col gap-3">
            <div className={`flex flex-wrap gap-4 items-start border rounded p-4 ${v.className}`}>
                {v.icon}
                <div className="flex-1 min-w-60">
                    <div className="text-lg font-semibold">{v.title}</div>
                    <p className="mb-0">{v.body}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                    {verdict === 'unused' ? (
                        <LemonButton type="primary" status="danger" onClick={() => stub('hide this property')}>
                            Hide property
                        </LemonButton>
                    ) : verdict === 'load-bearing' ? (
                        <LemonButton type="primary" onClick={() => stub('verify this property')}>
                            Verify property
                        </LemonButton>
                    ) : (
                        <LemonButton type="secondary" onClick={() => stub('message the people who use it')}>
                            Ask the people using it
                        </LemonButton>
                    )}
                </div>
            </div>

            <ul className="flex flex-col gap-1.5 list-none p-0 m-0">
                <Check ok={usage.queries30d > 0} source="pr">
                    {usage.queries30d > 0 ? (
                        <>
                            <b>{usage.queries30d.toLocaleString()} queries</b> in the last 30 days
                            {usage.lastQueriedAt && (
                                <>
                                    , last <TZLabel time={usage.lastQueriedAt} />
                                </>
                            )}
                        </>
                    ) : (
                        'No queries in the last 30 days'
                    )}
                    {trendDown && (
                        <span className="text-warning">
                            {' '}
                            (down from {usage.queriesPrior30d.toLocaleString()} the 30 days before)
                        </span>
                    )}
                </Check>
                <Check ok={usage.people.length > 0} source="new">
                    {usage.people.length > 0 ? (
                        <>
                            Queried by <b>{usage.people.length}</b> {usage.people.length === 1 ? 'person' : 'people'}:{' '}
                            {usage.people
                                .slice(0, 3)
                                .map((p) => p.first_name)
                                .join(', ')}
                            {usage.people.length > 3 && ` and ${usage.people.length - 3} more`}
                        </>
                    ) : (
                        'Nobody queried it'
                    )}
                </Check>
                <Check ok={usage.insights.length > 0} source="pr">
                    {usage.insights.length > 0 ? (
                        <>
                            Used in <b>{usage.insights.length}</b> saved insight{usage.insights.length === 1 ? '' : 's'}
                            {dashboards.size > 0 && (
                                <>
                                    {' '}
                                    on <b>{dashboards.size}</b> dashboard{dashboards.size === 1 ? '' : 's'}
                                </>
                            )}
                        </>
                    ) : (
                        'No saved insight uses it'
                    )}
                </Check>
                <Check ok={activeRefs.length > 0} source="new">
                    {activeRefs.length > 0 ? (
                        <>
                            Active in{' '}
                            {activeRefs.map((r, i) => (
                                <span key={r.name}>
                                    {i > 0 && ', '}
                                    {r.kind.toLowerCase()} <b>{r.name}</b>
                                </span>
                            ))}
                        </>
                    ) : (
                        'No active feature flag, cohort, or experiment uses it'
                    )}
                </Check>
                <Check ok={!!usage.lastIngestedAt} source="new">
                    {usage.lastIngestedAt ? (
                        <>
                            Still ingested, last seen <TZLabel time={usage.lastIngestedAt} /> on{' '}
                            {usage.seenOnEvents.map((e) => e.name).join(', ')}
                        </>
                    ) : (
                        'Not ingested any more'
                    )}
                </Check>
            </ul>

            {usage.insights.length > 0 && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'insights',
                            header: `What breaks if you rename it (${usage.insights.length} insights)`,
                            content: (
                                <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                                    {usage.insights.map((insight) => (
                                        <li key={insight.short_id} className="flex flex-wrap gap-2 items-center">
                                            <Link to={urls.insightView(insight.short_id as any)}>{insight.name}</Link>
                                            <span className="text-secondary text-xs">
                                                {insight.roles.map((r) => ROLE_LABELS[r]).join(', ')} ·{' '}
                                                {insight.views30d.toLocaleString()} views
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}

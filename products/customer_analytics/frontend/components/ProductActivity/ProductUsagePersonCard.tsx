import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { BookActivityPerson, BookActivityPersonFirstUse } from '~/queries/schema/schema-general'

import { getProductUsagePathShares } from './productUsagePresentation'

function PersonMetric({ label, value }: { label: string; value: string | null }): JSX.Element {
    return (
        <div className="flex flex-col min-w-0">
            <span className="text-xs text-secondary">{label}</span>
            <span className={value ? 'font-semibold' : 'text-tertiary'}>{value ?? '-'}</span>
        </div>
    )
}

export function ProductUsagePersonCard({
    person,
    firstUse,
    isNew,
}: {
    person: BookActivityPerson
    firstUse?: BookActivityPersonFirstUse
    isNew: boolean
}): JSX.Element {
    const paths = getProductUsagePathShares(person.topPaths)
    return (
        <div
            className="flex flex-col gap-3 border border-primary rounded-lg p-3 bg-surface-primary"
            data-attr="product-usage-person-card"
        >
            <div className="flex items-center justify-between gap-2 min-w-0">
                <strong className="truncate" title={person.label}>
                    {person.label}
                </strong>
                {firstUse && (
                    <LemonTag type={isNew ? 'success' : 'muted'} className="shrink-0">
                        {isNew ? (
                            'First use this week'
                        ) : (
                            <TZLabel time={firstUse.date} formatDate="[First use] MMM D, YYYY" formatTime="" />
                        )}
                    </LemonTag>
                )}
            </div>
            <div className="grid grid-cols-3 gap-3">
                <PersonMetric
                    label="Time on pages"
                    value={person.engagedSeconds ? humanFriendlyDuration(person.engagedSeconds) : null}
                />
                <PersonMetric label="Actions" value={person.actionCount ? String(person.actionCount) : null} />
                <PersonMetric label="Agent calls" value={person.agentCalls ? String(person.agentCalls) : null} />
            </div>
            {paths.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs text-secondary">Top pages</span>
                    {paths.map((path) => (
                        <div
                            key={path.path}
                            className="grid grid-cols-[minmax(0,1fr)_6rem_4.5rem] items-center gap-2 text-xs"
                        >
                            <span className="font-mono truncate" title={path.path}>
                                {path.path}
                            </span>
                            <span
                                className="h-1.5 rounded-full bg-surface-secondary overflow-hidden"
                                aria-hidden="true"
                            >
                                <span
                                    className="block h-full rounded-full bg-accent"
                                    style={{ width: `${path.share * 100}%` }}
                                />
                            </span>
                            <span className="text-right text-secondary">{humanFriendlyDuration(path.seconds)}</span>
                        </div>
                    ))}
                </div>
            )}
            {person.actions.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs text-secondary">Actions</span>
                    <div className="flex flex-wrap gap-1">
                        {person.actions.map((action) => (
                            <LemonTag key={action.event} type="muted">
                                {`${action.event} × ${action.count}`}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

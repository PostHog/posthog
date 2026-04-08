import { IconTrash, IconPencil } from '@posthog/icons'
import { LemonButton, LemonTag, LemonSnack } from '@posthog/lemon-ui'

import { IconSubArrowRight } from 'lib/lemon-ui/icons'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

export interface TriggerGroupCardProps {
    group: SessionRecordingTriggerGroup
    onEdit?: () => void
    onDelete?: (id: string) => void
}

interface ConditionRowProps {
    type: 'events' | 'urls' | 'flag'
    values: string[]
    matchType: 'any' | 'all'
}

function ConditionRow({ type, values, matchType, isFirst }: ConditionRowProps & { isFirst: boolean }): JSX.Element {
    const labels = {
        events: 'Event',
        urls: 'User has visited URL matching pattern',
        flag: 'Feature flag',
    }

    const actions = {
        events: 'occurred',
        urls: '',
        flag: 'is enabled',
    }

    // For "any" match type, always use arrow. For "all", use & after first row
    const showArrow = matchType === 'any' || isFirst

    return (
        <div className="flex items-center gap-1.5 flex-wrap text-sm">
            {showArrow ? (
                <LemonButton icon={<IconSubArrowRight className="arrow-right" />} size="small" noPadding />
            ) : (
                <LemonButton icon={<span className="text-xs font-medium">&</span>} size="small" noPadding />
            )}
            <span className="text-muted">{labels[type]}</span>
            {values.map((value, idx) => (
                <span key={value} className="contents">
                    {idx > 0 && <span className="text-muted text-xs">or</span>}
                    <LemonSnack>{value}</LemonSnack>
                </span>
            ))}
            <span className="text-muted">{actions[type]}</span>
        </div>
    )
}

export function TriggerGroupCard({ group, onEdit, onDelete }: TriggerGroupCardProps): JSX.Element {
    const { id, name, sampleRate, minDurationMs, conditions } = group

    // Format display name
    const displayName = name || `Trigger group ${id.slice(0, 8)}`

    // Build condition rows - group same types together
    const conditionRows: ConditionRowProps[] = []

    if (conditions.events && conditions.events.length > 0) {
        conditionRows.push({
            type: 'events',
            values: conditions.events,
            matchType: conditions.matchType,
        })
    }

    if (conditions.urls && conditions.urls.length > 0) {
        conditionRows.push({
            type: 'urls',
            values: conditions.urls.map((urlConfig) => urlConfig.url),
            matchType: conditions.matchType,
        })
    }

    if (conditions.flag) {
        const flagKey = typeof conditions.flag === 'string' ? conditions.flag : conditions.flag.key
        conditionRows.push({
            type: 'flag',
            values: [flagKey],
            matchType: conditions.matchType,
        })
    }

    const hasConditions = conditionRows.length > 0
    const matchType = conditions.matchType === 'any' ? 'any' : 'all'

    return (
        <div className="border rounded p-3 bg-surface-primary">
            {/* Header row: Name and actions */}
            <div className="flex items-center justify-between gap-4 mb-2">
                <div className="flex-1">
                    <h3 className="mb-0">{displayName}</h3>
                </div>
                <div className="flex items-center gap-4">
                    <div className="flex gap-2">
                        <LemonButton size="small" icon={<IconPencil />} onClick={onEdit}>
                            Edit
                        </LemonButton>
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            onClick={onDelete ? () => onDelete(id) : undefined}
                            disabledReason={!onDelete ? 'Delete not yet implemented' : undefined}
                        >
                            Delete
                        </LemonButton>
                    </div>
                </div>
            </div>
            <div className="flex flex-row items-center">
                {/* Match type description */}
                <div className="flex flex-col w-full">
                    <div className="mb-3">
                        <span className="text-sm">
                            {hasConditions ? (
                                <>
                                    Match <b>sessions</b> against{' '}
                                    <LemonTag type="success" className="uppercase">
                                        {matchType}
                                    </LemonTag>{' '}
                                    criteria
                                </>
                            ) : (
                                <>
                                    Trigger group will match{' '}
                                    <LemonTag type="success" size="medium">
                                        all sessions
                                    </LemonTag>
                                </>
                            )}
                        </span>
                    </div>

                    {/* Conditions */}
                    {hasConditions && (
                        <div className="flex flex-col gap-1 mb-3">
                            {conditionRows.map((row, idx) => (
                                <ConditionRow key={idx} {...row} isFirst={idx === 0} />
                            ))}
                        </div>
                    )}

                    {/* Minimum duration */}
                    {minDurationMs !== undefined && minDurationMs > 0 && (
                        <div className="text-sm text-muted">
                            Minimum duration: <b>{minDurationMs / 1000}</b> seconds
                        </div>
                    )}
                </div>
                <div className="text-right flex-col w-100">
                    <div className="text-2xl font-semibold leading-none">{Math.round(sampleRate * 100)}%</div>
                    <div className="text-xs text-muted">sample rate</div>
                </div>
            </div>
        </div>
    )
}

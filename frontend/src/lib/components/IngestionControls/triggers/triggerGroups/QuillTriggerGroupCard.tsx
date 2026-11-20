import { IconPencil, IconTrash } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { QuillTriggerGroupConditionRow } from './QuillTriggerGroupConditionRow'
import { QuillTriggerGroupMatchSummary } from './QuillTriggerGroupMatchSummary'
import { TriggerGroupCardProps } from './TriggerGroupCard'
import { buildConditionRows, triggerGroupDisplayName } from './triggerGroupHelpers'

export function QuillTriggerGroupCard({ group, onEdit, onDelete }: TriggerGroupCardProps): JSX.Element {
    const { id, name, sampleRate, minDurationMs, conditions } = group

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const conditionRows = buildConditionRows(conditions)
    const hasConditions = conditionRows.length > 0

    return (
        <Card size="sm">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                <CardTitle>{triggerGroupDisplayName(name, id)}</CardTitle>
                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="outline"
                        onClick={onEdit}
                        disabledReason={restrictedReason}
                        data-attr="trigger-group-edit"
                    >
                        <IconPencil />
                        Edit
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={onDelete ? () => onDelete(id) : undefined}
                        disabledReason={restrictedReason ?? (!onDelete ? 'Delete not yet implemented' : undefined)}
                        data-attr="trigger-group-delete"
                    >
                        <IconTrash />
                        Delete
                    </Button>
                </div>
            </CardHeader>
            <CardContent className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <QuillTriggerGroupMatchSummary
                        hasConditions={hasConditions}
                        matchType={conditions.matchType === 'any' ? 'any' : 'all'}
                    />
                    {hasConditions && (
                        <div className="flex flex-col gap-1">
                            {conditionRows.map((row, idx) => (
                                <QuillTriggerGroupConditionRow key={idx} {...row} isFirst={idx === 0} />
                            ))}
                        </div>
                    )}
                    {minDurationMs !== undefined && minDurationMs > 0 && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Minimum duration: <b>{minDurationMs / 1000}</b> seconds
                        </Text>
                    )}
                </div>
                <div className="flex flex-col items-end">
                    <Text size="lg" weight="semibold" render={<span className="leading-none" />}>
                        {Math.round(sampleRate * 100)}%
                    </Text>
                    <Text size="xs" variant="muted" render={<span />}>
                        sample rate
                    </Text>
                </div>
            </CardContent>
        </Card>
    )
}

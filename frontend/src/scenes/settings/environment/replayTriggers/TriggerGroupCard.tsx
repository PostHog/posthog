import { IconTrash, IconPencil } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

export interface TriggerGroupCardProps {
    group: SessionRecordingTriggerGroup
}

export function TriggerGroupCard({ group }: TriggerGroupCardProps): JSX.Element {
    const { id, name, sampleRate, minDurationMs, conditions } = group

    // TODO: Format conditions for display
    const conditionsSummary = `${conditions.matchType.toUpperCase()} match`

    return (
        <div className="border rounded p-4">
            <div className="flex items-start justify-between">
                <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                        <h4 className="font-semibold">{name || `Group ${id.slice(0, 8)}`}</h4>
                        <LemonTag type="default">{Math.round(sampleRate * 100)}% sampled</LemonTag>
                        {minDurationMs !== undefined && <LemonTag type="muted">min {minDurationMs / 1000}s</LemonTag>}
                    </div>
                    <p className="text-sm text-muted">{conditionsSummary}</p>
                    {/* TODO: Show detailed conditions */}
                </div>
                <div className="flex gap-2">
                    <LemonButton size="small" icon={<IconPencil />} disabled>
                        Edit
                    </LemonButton>
                    <LemonButton size="small" icon={<IconTrash />} status="danger" disabled>
                        Delete
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

import { replayTriggersV2Logic } from './replayTriggersV2Logic'
import { TriggerGroupCard } from './TriggerGroupCard'

export function TriggerGroupsEditor(): JSX.Element {
    const { triggerGroups, isLoading } = useValues(replayTriggersV2Logic)

    if (isLoading) {
        return <div>Loading...</div>
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="font-semibold mb-1">Trigger Groups</h3>
                    <p className="text-muted text-sm">
                        Define multiple trigger groups with different sampling rates and conditions.
                    </p>
                </div>
                <LemonButton type="primary" icon={<IconPlus />} disabled>
                    Add Group
                </LemonButton>
            </div>

            {triggerGroups.length === 0 ? (
                <div className="border border-dashed rounded p-6 text-center text-muted">
                    <p>No trigger groups configured.</p>
                    <p className="text-xs mt-2">Add a group to start recording based on specific conditions.</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {triggerGroups.map((group: SessionRecordingTriggerGroup) => (
                        <TriggerGroupCard key={group.id} group={group} />
                    ))}
                </div>
            )}

            {/* TODO: Add evaluation mode selector */}
            {/* TODO: Add fallback sample rate */}
        </div>
    )
}

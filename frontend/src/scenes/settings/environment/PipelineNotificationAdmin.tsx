import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { PIPELINE_KIND_LABELS, PIPELINE_KIND_ORDER } from '../shared/pipelineDiscovery'
import { pipelineNotificationAdminLogic } from './pipelineNotificationAdminLogic'
import { PipelineNotificationRow } from './PipelineNotificationRow'

export function PipelineNotificationAdmin(): JSX.Element {
    const { members, pipelines, pendingChangeCount, affectedMemberCount, savingChanges } =
        useValues(pipelineNotificationAdminLogic)
    const { discardChanges, saveChanges } = useActions(pipelineNotificationAdminLogic)

    if (members === null || pipelines === null) {
        return (
            <div className="flex items-center gap-2 py-2">
                <Spinner className="text-lg" />
                <span className="text-muted text-sm">Loading pipelines...</span>
            </div>
        )
    }

    if (pipelines.length === 0) {
        return <p className="text-muted text-sm">This project has no data pipelines yet.</p>
    }

    const confirmSave = (): void => {
        LemonDialog.open({
            title: 'Save these notification settings?',
            description: `This changes data pipeline failure emails for ${affectedMemberCount} ${
                affectedMemberCount === 1 ? 'member' : 'members'
            }. Everyone affected gets a notification in the app, and can change it back themselves.`,
            primaryButton: { children: 'Save', onClick: saveChanges },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="space-y-3">
            <p className="text-muted text-sm">
                Members receive failure emails for every pipeline by default. Uncheck a member to stop sending them
                emails for that pipeline. They can turn it back on in their own notification settings.
            </p>

            {PIPELINE_KIND_ORDER.filter((kind) => pipelines.some((pipeline) => pipeline.kind === kind)).map((kind) => (
                <div key={kind} className="space-y-2">
                    <h4 className="mb-0">{PIPELINE_KIND_LABELS[kind]}</h4>
                    {pipelines
                        .filter((pipeline) => pipeline.kind === kind)
                        .map((pipeline) => (
                            <PipelineNotificationRow key={pipeline.id} pipeline={pipeline} />
                        ))}
                </div>
            ))}

            {pendingChangeCount > 0 && (
                <div className="sticky bottom-0 flex items-center justify-between gap-2 border rounded p-3 bg-surface-primary">
                    <span className="text-sm">
                        {pendingChangeCount} {pendingChangeCount === 1 ? 'change' : 'changes'} pending for{' '}
                        {affectedMemberCount} {affectedMemberCount === 1 ? 'member' : 'members'}
                    </span>
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={discardChanges}
                            disabledReason={savingChanges ? 'Saving' : undefined}
                            data-attr="pipeline-notification-admin-discard"
                        >
                            Discard
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={confirmSave}
                            loading={savingChanges}
                            disabledReason={savingChanges ? 'Saving' : undefined}
                            data-attr="pipeline-notification-admin-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { NOTIFICATION_CONCEPTS } from '../shared/notificationSettingDescriptors'
import { NotificationConceptRow } from './NotificationConceptRow'
import { notificationGovernanceLogic } from './notificationGovernanceLogic'

export function NotificationGovernanceSetting(): JSX.Element {
    const { members, pendingChangeCount, affectedMemberCount, savingChanges } = useValues(notificationGovernanceLogic)
    const { discardChanges, saveChanges } = useActions(notificationGovernanceLogic)

    if (members === null) {
        return (
            <div className="flex items-center gap-2 py-2">
                <Spinner className="text-lg" />
                <span className="text-muted text-sm">Loading members...</span>
            </div>
        )
    }

    if (members.length === 0) {
        return <p className="text-muted text-sm">This organization has no members yet.</p>
    }

    const confirmSave = (): void => {
        LemonDialog.open({
            title: 'Save these notification settings?',
            description: `This changes email notifications for ${affectedMemberCount} ${
                affectedMemberCount === 1 ? 'member' : 'members'
            }. Everyone affected gets a notification in the app.`,
            primaryButton: { children: 'Save', onClick: saveChanges },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="deprecated-space-y-3">
            <LemonBanner type="info">
                These settings belong to the person rather than to one organization, so an override you set here also
                applies to that member's other organizations, if they belong to any.
            </LemonBanner>

            {NOTIFICATION_CONCEPTS.map((concept) => (
                <NotificationConceptRow key={concept.setting} concept={concept} />
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
                            data-attr="notification-governance-discard"
                        >
                            Discard
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={confirmSave}
                            loading={savingChanges}
                            disabledReason={savingChanges ? 'Saving' : undefined}
                            data-attr="notification-governance-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

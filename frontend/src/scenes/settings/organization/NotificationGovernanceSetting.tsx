import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { LOCKABLE_NOTIFICATION_SETTINGS } from '../shared/notificationSettingDescriptors'
import { notificationGovernanceLogic } from './notificationGovernanceLogic'
import { NotificationGovernanceRow } from './NotificationGovernanceRow'

export function NotificationGovernanceSetting(): JSX.Element {
    const { members, pipelines, pendingChangeCount, affectedMemberCount, savingChanges } =
        useValues(notificationGovernanceLogic)
    const { discardChanges, saveChanges } = useActions(notificationGovernanceLogic)

    if (members === null || pipelines === null) {
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
        <div className="space-y-3">
            <p className="text-muted text-sm">
                Set an email notification for your members and they cannot change it back themselves. Anything you leave
                alone stays under their own control. Removing a setting here gives them their own choice back.
            </p>
            <LemonBanner type="info">
                These settings belong to the person rather than to one organization, so a setting you fix here also
                applies to that member's other organizations, if they belong to any.
            </LemonBanner>

            {LOCKABLE_NOTIFICATION_SETTINGS.map((descriptor) => (
                <NotificationGovernanceRow key={descriptor.setting} descriptor={descriptor} />
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

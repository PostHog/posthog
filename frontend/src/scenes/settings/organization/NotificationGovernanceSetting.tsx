import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { pluralize } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { NOTIFICATION_CONCEPTS } from '../shared/notificationSettingDescriptors'
import { NotificationConceptRow } from './NotificationConceptRow'
import { notificationGovernanceLogic } from './notificationGovernanceLogic'

export function NotificationGovernanceSetting(): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    // PayGateMini falls through to its children when billing carries no metadata for the feature,
    // so the entitlement is checked here too. Otherwise the list below mounts and its first
    // request comes back as a payment prompt.
    const entitled = hasAvailableFeature(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)

    return (
        <PayGateMini
            feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
            featureDetail="organization-member-notifications"
        >
            {entitled ? <MemberNotifications /> : null}
        </PayGateMini>
    )
}

function MemberNotifications(): JSX.Element {
    const { members, pendingChangeCount, affectedMemberCount, savingChanges, loadFailed } =
        useValues(notificationGovernanceLogic)
    const { discardChanges, saveChanges, loadMembers } = useActions(notificationGovernanceLogic)

    if (loadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadMembers }}
                data-attr="notification-governance-load-failed"
            >
                Couldn't load your members. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

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
            description: `This changes email notifications for ${pluralize(
                affectedMemberCount,
                'member'
            )}. Everyone affected gets a notification in the app.`,
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
                <div className="sticky bottom-0 z-10 flex items-center justify-between gap-2 border rounded p-3 bg-surface-primary">
                    <span className="text-sm">
                        {pluralize(pendingChangeCount, 'change')} pending for {pluralize(affectedMemberCount, 'member')}
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
